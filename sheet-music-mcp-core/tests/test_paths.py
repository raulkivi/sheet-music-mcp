"""Read and write confinement (docs/conventions.md, Score References: Read policy)."""

import os
import re
from pathlib import Path

import pytest

from sheet_music_mcp_core import paths
from sheet_music_mcp_core.errors import ProcessingError
from sheet_music_mcp_core.paths import (
    SCORE_SUFFIXES,
    PathPolicyError,
    confine_output_path,
    confine_read_path,
    input_roots,
    max_score_bytes,
    new_output_path,
    output_root,
    read_roots,
)

SECRET = "root:x:0:0:secret-line"


@pytest.fixture
def root(tmp_path, monkeypatch):
    """An output root with no extra input roots."""
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(out))
    monkeypatch.delenv("SHEET_MUSIC_INPUT_ROOTS", raising=False)
    return out.resolve()


def _confine(path, roots, *, max_bytes=1000, param="musicxml_path"):
    return confine_read_path(path, roots=roots, suffixes=SCORE_SUFFIXES, max_bytes=max_bytes, param=param)


def _outside_file(tmp_path, name="secret.musicxml"):
    outside = tmp_path / "elsewhere"
    outside.mkdir(exist_ok=True)
    secret = outside / name
    secret.write_text(SECRET)
    return secret


class TestPathPolicyError:
    def test_is_a_processing_error_and_a_value_error(self):
        error = PathPolicyError("x", "INVALID_PARAMETER")

        assert isinstance(error, ProcessingError)
        assert isinstance(error, ValueError)
        assert error.error_code == "INVALID_PARAMETER"


class TestSettings:
    def test_score_suffixes(self):
        assert SCORE_SUFFIXES == (".musicxml", ".xml", ".mxl")

    def test_max_score_bytes_defaults_to_16_mib(self, monkeypatch):
        monkeypatch.delenv("SHEET_MUSIC_MAX_SCORE_BYTES", raising=False)

        assert max_score_bytes() == 16 * 1024 * 1024

    def test_max_score_bytes_from_environment(self, monkeypatch):
        monkeypatch.setenv("SHEET_MUSIC_MAX_SCORE_BYTES", "2048")

        assert max_score_bytes() == 2048

    @pytest.mark.parametrize("value", ["", "lots", "0", "-5"])
    def test_invalid_max_score_bytes_falls_back_to_default(self, monkeypatch, value):
        monkeypatch.setenv("SHEET_MUSIC_MAX_SCORE_BYTES", value)

        assert max_score_bytes() == 16 * 1024 * 1024

    def test_output_root_defaults_to_working_directory(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SHEET_MUSIC_OUTPUT_ROOT", raising=False)
        monkeypatch.chdir(tmp_path)

        assert output_root() == tmp_path.resolve()

    def test_output_root_from_environment(self, root):
        assert output_root() == root

    def test_input_roots_split_on_pathsep_ignoring_blanks(self, tmp_path, monkeypatch):
        a, b = tmp_path / "a", tmp_path / "b"
        monkeypatch.setenv("SHEET_MUSIC_INPUT_ROOTS", f"{a}{os.pathsep}{os.pathsep} {os.pathsep}{b}")

        assert input_roots() == [a.resolve(), b.resolve()]

    def test_no_input_roots_by_default(self, monkeypatch):
        monkeypatch.delenv("SHEET_MUSIC_INPUT_ROOTS", raising=False)

        assert input_roots() == []

    def test_read_roots_order_output_client_input_without_duplicates(self, root, tmp_path, monkeypatch):
        client, extra = tmp_path / "client", tmp_path / "extra"
        monkeypatch.setenv("SHEET_MUSIC_INPUT_ROOTS", os.pathsep.join([str(extra), str(root)]))

        roots = read_roots([client, str(root), client])

        assert roots == [root, client.resolve(), extra.resolve()]

    def test_read_roots_defaults_to_output_root(self, root):
        assert read_roots() == [root]


class TestConfineReadPath:
    def test_file_inside_root_is_returned_resolved(self, root):
        (root / "a.musicxml").write_text("<x/>")

        result = _confine(str(root / "a.musicxml"), [root])

        assert isinstance(result, Path)
        assert result == root / "a.musicxml"

    def test_relative_path_resolves_against_output_root(self, root, tmp_path, monkeypatch):
        (root / "a.xml").write_text("<x/>")
        monkeypatch.chdir(tmp_path)

        assert _confine("a.xml", [root]) == root / "a.xml"

    def test_home_is_expanded(self, root, monkeypatch):
        monkeypatch.setenv("HOME", str(root))
        (root / "h.mxl").write_bytes(b"PK")

        assert _confine("~/h.mxl", [root]) == root / "h.mxl"

    def test_suffix_check_ignores_case(self, root):
        (root / "A.MusicXML").write_text("<x/>")

        assert _confine("A.MusicXML", [root]) == root / "A.MusicXML"

    def test_etc_passwd_is_outside_the_roots(self, root):
        with pytest.raises(PathPolicyError) as info:
            _confine("/etc/passwd", [root])

        error = info.value
        assert error.error_code == "INVALID_PARAMETER"
        assert str(error) == "musicxml_path must be inside one of the allowed folders"
        assert str(root) in error.hint
        assert "SHEET_MUSIC_INPUT_ROOTS" in error.hint
        assert "root:" not in str(error) + error.hint

    def test_parent_traversal_is_rejected(self, root, tmp_path):
        _outside_file(tmp_path, "x.musicxml")

        with pytest.raises(PathPolicyError) as info:
            _confine("../elsewhere/x.musicxml", [root])

        assert info.value.error_code == "INVALID_PARAMETER"
        assert SECRET not in str(info.value)

    def test_symlink_pointing_out_is_rejected(self, root, tmp_path):
        secret = _outside_file(tmp_path)
        (root / "link.musicxml").symlink_to(secret)

        with pytest.raises(PathPolicyError) as info:
            _confine("link.musicxml", [root])

        assert info.value.error_code == "INVALID_PARAMETER"
        assert SECRET not in str(info.value) + (info.value.hint or "")

    def test_symlink_inside_the_roots_is_followed(self, root):
        (root / "real.musicxml").write_text("<x/>")
        (root / "alias.musicxml").symlink_to(root / "real.musicxml")

        assert _confine("alias.musicxml", [root]) == root / "real.musicxml"

    def test_missing_file_outside_roots_does_not_reveal_existence(self, root, tmp_path):
        with pytest.raises(PathPolicyError) as info:
            _confine(str(tmp_path / "nowhere" / "missing.musicxml"), [root])

        assert info.value.error_code == "INVALID_PARAMETER"

    def test_wrong_suffix(self, root):
        (root / "notes.txt").write_text("hello")

        with pytest.raises(PathPolicyError) as info:
            _confine("notes.txt", [root])

        assert info.value.error_code == "INVALID_PARAMETER"
        assert str(info.value) == "musicxml_path must end with one of .musicxml, .xml, .mxl"

    def test_suffix_is_checked_after_resolving_symlinks(self, root):
        (root / "secret.txt").write_text("hello")
        (root / "score.musicxml").symlink_to(root / "secret.txt")

        with pytest.raises(PathPolicyError) as info:
            _confine("score.musicxml", [root])

        assert info.value.error_code == "INVALID_PARAMETER"

    def test_missing_file_inside_root(self, root):
        with pytest.raises(PathPolicyError) as info:
            _confine("missing.musicxml", [root])

        assert info.value.error_code == "FILE_NOT_FOUND"

    def test_directory_is_not_a_file(self, root):
        (root / "folder.musicxml").mkdir()

        with pytest.raises(PathPolicyError) as info:
            _confine("folder.musicxml", [root])

        assert info.value.error_code == "FILE_NOT_FOUND"

    def test_too_large(self, root):
        (root / "big.musicxml").write_bytes(b"x" * 1001)

        with pytest.raises(PathPolicyError) as info:
            _confine("big.musicxml", [root], max_bytes=1000)

        assert info.value.error_code == "FILE_TOO_LARGE"
        assert "1000" in str(info.value)

    def test_exactly_at_size_limit_is_accepted(self, root):
        (root / "edge.musicxml").write_bytes(b"x" * 1000)

        assert _confine("edge.musicxml", [root], max_bytes=1000) == root / "edge.musicxml"

    def test_param_names_the_parameter(self, root):
        with pytest.raises(PathPolicyError, match="^reference_path must be inside"):
            _confine("/etc/passwd", [root], param="reference_path")

    def test_input_roots_extend_the_allowed_set(self, root, tmp_path, monkeypatch):
        score = _outside_file(tmp_path, "shared.musicxml")
        monkeypatch.setenv("SHEET_MUSIC_INPUT_ROOTS", str(score.parent))

        assert _confine(str(score), read_roots()) == score.resolve()

    def test_client_roots_extend_the_allowed_set(self, root, tmp_path):
        score = _outside_file(tmp_path, "client.musicxml")

        assert _confine(str(score), read_roots([score.parent])) == score.resolve()

    def test_unresolved_roots_are_resolved(self, root, tmp_path):
        (root / "a.musicxml").write_text("<x/>")
        indirect = tmp_path / "out" / ".." / "out"

        assert _confine(str(root / "a.musicxml"), [indirect]) == root / "a.musicxml"

    def test_no_roots_allows_nothing(self, root):
        (root / "a.musicxml").write_text("<x/>")

        with pytest.raises(PathPolicyError) as info:
            _confine("a.musicxml", [])

        assert info.value.error_code == "INVALID_PARAMETER"


class TestConfineOutputPath:
    """Moved unchanged from render-mcp, synth-mcp and omr-mcp (tests/test_utils.py)."""

    def _confine(self, path, tmp_path, monkeypatch, suffixes=(".pdf",)):
        monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(tmp_path))
        return confine_output_path(path, suffixes)

    def test_returns_provided_path_inside_root(self, tmp_path, monkeypatch):
        out = self._confine(str(tmp_path / "score.pdf"), tmp_path, monkeypatch)
        assert out == str((tmp_path / "score.pdf").resolve())

    def test_relative_path_lands_in_root(self, tmp_path, monkeypatch):
        out = self._confine("a.pdf", tmp_path, monkeypatch)
        assert out == str((tmp_path / "a.pdf").resolve())

    def test_rejects_parent_traversal(self, tmp_path, monkeypatch):
        with pytest.raises(ValueError, match="inside"):
            self._confine("../escape.pdf", tmp_path, monkeypatch)

    def test_rejects_absolute_path_outside_root(self, tmp_path, monkeypatch):
        with pytest.raises(ValueError, match="inside"):
            self._confine("/etc/cron.d/x.pdf", tmp_path, monkeypatch)

    def test_rejects_symlink_escape(self, tmp_path, monkeypatch):
        outside = tmp_path / "outside"
        outside.mkdir()
        root = tmp_path / "root"
        root.mkdir()
        (root / "link").symlink_to(outside)
        with pytest.raises(ValueError, match="inside"):
            self._confine("link/x.pdf", root, monkeypatch)

    def test_rejects_wrong_suffix(self, tmp_path, monkeypatch):
        with pytest.raises(ValueError, match="end with"):
            self._confine("notes.sh", tmp_path, monkeypatch)

    def test_rejects_existing_file(self, tmp_path, monkeypatch):
        (tmp_path / "a.pdf").write_text("x")
        with pytest.raises(ValueError, match="exists"):
            self._confine("a.pdf", tmp_path, monkeypatch)

    def test_same_messages_as_the_server_copies(self, tmp_path, monkeypatch):
        root = tmp_path.resolve()
        (tmp_path / "a.wav").write_text("x")
        cases = {
            "/etc/x.wav": f"output_path must be inside {root}",
            "a.mp3": "output_path must end with one of .wav, .flac",
            "a.wav": f"output_path already exists: {root / 'a.wav'}",
        }
        for path, message in cases.items():
            with pytest.raises(PathPolicyError) as info:
                self._confine(path, tmp_path, monkeypatch, suffixes=(".wav", ".flac"))
            assert str(info.value) == message
            assert info.value.error_code == "INVALID_PARAMETER"


class TestNewOutputPath:
    def test_named_by_stem_and_timestamp_under_scores(self, root):
        path = new_output_path("recognized", ".musicxml")

        assert path.parent == root / "scores"
        assert re.fullmatch(r"recognized-\d{8}-\d{6}-\d{6}\.musicxml", path.name)
        assert not path.exists()

    def test_folder_is_private(self, root):
        new_output_path("x", ".musicxml")

        assert (root / "scores").stat().st_mode & 0o077 == 0

    def test_custom_subdir(self, root):
        assert new_output_path("x", ".wav", subdir="audio").parent == root / "audio"

    def test_never_overwrites(self, root, monkeypatch):
        monkeypatch.setattr(paths, "_timestamp", lambda: "20261027-120000-000001")
        first = new_output_path("score", ".musicxml")
        first.write_text("taken")
        second = new_output_path("score", ".musicxml")
        second.write_text("taken")
        third = new_output_path("score", ".musicxml")

        assert first.name == "score-20261027-120000-000001.musicxml"
        assert second.name == "score-20261027-120000-000001-1.musicxml"
        assert third.name == "score-20261027-120000-000001-2.musicxml"

    def test_stem_cannot_leave_the_folder(self, root):
        path = new_output_path("../../evil name/x", ".musicxml")

        assert path.parent == root / "scores"
        assert "/" not in path.name and " " not in path.name

    def test_empty_stem_gets_a_default(self, root):
        assert new_output_path("", ".musicxml").name.startswith("score-")

    def test_folder_symlinked_out_of_the_root_is_rejected(self, root, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        (root / "scores").symlink_to(outside)

        with pytest.raises(PathPolicyError):
            new_output_path("x", ".musicxml")
