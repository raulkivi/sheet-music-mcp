"""The bridge to synth-mcp's venv: one part of a score rendered to a WAV in a subprocess."""

import subprocess
from pathlib import Path

import pytest

from . import synth_bridge


def fake_synth(tmp_path: Path) -> Path:
    python = tmp_path / "synth-mcp" / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("")
    (tmp_path / "synth-mcp" / "tests").mkdir()
    (tmp_path / "synth-mcp" / "tests" / "render_part.py").write_text("")
    return tmp_path / "synth-mcp"


class Recorder:
    def __init__(self, returncode=0, stderr=""):
        self.calls = []
        self.returncode, self.stderr = returncode, stderr

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, self.returncode, "", self.stderr)


def test_renders_one_part_with_synths_own_interpreter(tmp_path):
    synth_dir = fake_synth(tmp_path)
    run = Recorder()
    out = tmp_path / "alto.wav"

    result = synth_bridge.render_part(
        tmp_path / "score.musicxml", "P2", out, soundfont="/sf/Tim.sf2", synth_dir=synth_dir, run=run
    )

    assert result == out
    (args, kwargs), = run.calls
    assert args == [
        str(synth_dir / ".venv" / "bin" / "python"),
        "-I",
        str(synth_dir / "tests" / "render_part.py"),
        str(tmp_path / "score.musicxml"),
        str(out),
        "--part",
        "P2",
        "--timbre",
        "score",
    ]
    assert kwargs.get("shell", False) is False
    assert kwargs["env"]["SYNTH_SOUNDFONT_PATH"] == "/sf/Tim.sf2"
    assert "VIRTUAL_ENV" not in kwargs["env"]  # pitch-mcp's venv must not leak into synth's


def test_timbre_is_passed_on(tmp_path):
    run = Recorder()
    synth_bridge.render_part(
        tmp_path / "s.musicxml", "S", tmp_path / "s.wav", soundfont="x.sf2", timbre="choir",
        synth_dir=fake_synth(tmp_path), run=run,
    )
    assert run.calls[0][0][-2:] == ["--timbre", "choir"]


def test_a_failed_render_raises_with_synths_message(tmp_path):
    run = Recorder(returncode=1, stderr="render_part: Part not found: 'Descant'")
    with pytest.raises(synth_bridge.RenderFailed, match="Descant"):
        synth_bridge.render_part(
            tmp_path / "s.musicxml", "Descant", tmp_path / "x.wav", soundfont="x.sf2",
            synth_dir=fake_synth(tmp_path), run=run,
        )


class TestUnavailableReason:
    def test_available(self, tmp_path):
        sf = tmp_path / "Tim.sf2"
        sf.write_bytes(b"")
        environ = {"SYNTH_SOUNDFONT_PATH": str(sf)}
        assert synth_bridge.unavailable_reason(environ, fake_synth(tmp_path)) is None

    def test_no_synth_venv(self, tmp_path):
        reason = synth_bridge.unavailable_reason({"SYNTH_SOUNDFONT_PATH": "x"}, tmp_path / "synth-mcp")
        assert "synth-mcp venv" in reason and "uv sync" in reason

    def test_no_soundfont_variable(self, tmp_path):
        reason = synth_bridge.unavailable_reason({}, fake_synth(tmp_path))
        assert "SYNTH_SOUNDFONT_PATH" in reason

    def test_soundfont_file_missing(self, tmp_path):
        environ = {"SYNTH_SOUNDFONT_PATH": str(tmp_path / "gone.sf2")}
        reason = synth_bridge.unavailable_reason(environ, fake_synth(tmp_path))
        assert "gone.sf2" in reason
