"""The command pitch-mcp's round trip runs in this venv: render one part of a score to a WAV."""

import pytest

from . import render_part
from .midi_helpers import FIXTURES, fake_render, melodic_tracks, read_midi


def capture(monkeypatch):
    seen = {}

    def render(midi_bytes, output_path):
        seen["midi"] = midi_bytes
        return fake_render(midi_bytes, output_path)

    monkeypatch.setattr(render_part, "synthesize_midi", render)
    return seen


def test_renders_only_the_named_part(tmp_path, monkeypatch):
    seen = capture(monkeypatch)
    out = tmp_path / "alto.wav"

    code = render_part.main([str(FIXTURES / "satb_4bars.musicxml"), str(out), "--part", "Alto"])

    assert code == 0
    assert out.is_file()
    _, tracks = read_midi(seen["midi"])
    pitches = [e.value for t in melodic_tracks(tracks) for e in t.of("note_on")]
    assert len(melodic_tracks(tracks)) == 1
    assert pitches == [69, 71, 73, 74]  # A4 B4 C#5 D5


def test_timbre_is_passed_through(tmp_path, monkeypatch):
    seen = capture(monkeypatch)
    args = [str(FIXTURES / "satb_4bars.musicxml"), str(tmp_path / "s.wav"), "--part", "P1"]

    render_part.main(args + ["--timbre", "organ"])

    _, tracks = read_midi(seen["midi"])
    programs = [e.value for t in melodic_tracks(tracks) for e in t.of("program")]
    assert programs and programs != [0]


def test_unknown_part_fails_with_a_message(tmp_path, monkeypatch, capsys):
    capture(monkeypatch)
    code = render_part.main(
        [str(FIXTURES / "satb_4bars.musicxml"), str(tmp_path / "x.wav"), "--part", "Descant"]
    )
    assert code != 0
    assert "Descant" in capsys.readouterr().err


def test_script_has_no_package_imports_of_tests():
    # pitch-mcp runs the file by path, so it must not depend on the tests package.
    source = (FIXTURES.parent / "render_part.py").read_text()
    assert "from ." not in source


@pytest.mark.parametrize("missing", [[], ["score.musicxml"]])
def test_missing_arguments_exit_with_usage(missing):
    with pytest.raises(SystemExit) as exc:
        render_part.main(missing)
    assert exc.value.code == 2
