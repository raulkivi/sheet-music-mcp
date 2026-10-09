"""Tests for synth_mcp.utils."""

import pytest

from synth_mcp.utils import (
    generate_output_path,
    validate_musicxml,
    validate_tempo_factor,
)

VALID_MUSICXML = """<?xml version="1.0"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Soprano</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1"></measure>
  </part>
</score-partwise>"""


class TestValidateMusicxml:
    def test_valid_score_partwise(self):
        ok, err = validate_musicxml(VALID_MUSICXML)
        assert ok is True
        assert err == ""

    def test_valid_score_timewise(self):
        xml = '<?xml version="1.0"?><score-timewise></score-timewise>'
        ok, err = validate_musicxml(xml)
        assert ok is True

    def test_empty_string(self):
        ok, err = validate_musicxml("")
        assert ok is False

    def test_whitespace_only(self):
        ok, err = validate_musicxml("   \n  ")
        assert ok is False

    def test_invalid_xml(self):
        ok, err = validate_musicxml("not xml at all")
        assert ok is False
        assert "Invalid XML" in err

    def test_wrong_root_element(self):
        ok, err = validate_musicxml("<html><body/></html>")
        assert ok is False
        assert "Not a MusicXML score" in err

    def test_xml_with_namespace(self):
        xml = (
            '<?xml version="1.0"?>'
            '<score-partwise xmlns="http://www.musicxml.org/schema"></score-partwise>'
        )
        ok, err = validate_musicxml(xml)
        assert ok is True


class TestValidateTempoFactor:
    def test_valid_1_0(self):
        ok, err = validate_tempo_factor(1.0)
        assert ok is True
        assert err == ""

    def test_valid_lower_bound(self):
        ok, err = validate_tempo_factor(0.25)
        assert ok is True

    def test_valid_upper_bound(self):
        ok, err = validate_tempo_factor(4.0)
        assert ok is True

    def test_valid_int(self):
        ok, err = validate_tempo_factor(2)
        assert ok is True

    def test_too_slow(self):
        ok, err = validate_tempo_factor(0.1)
        assert ok is False
        assert "0.25" in err

    def test_too_fast(self):
        ok, err = validate_tempo_factor(5.0)
        assert ok is False
        assert "4.0" in err

    def test_just_below_lower_bound(self):
        ok, err = validate_tempo_factor(0.24)
        assert ok is False

    def test_just_above_upper_bound(self):
        ok, err = validate_tempo_factor(4.01)
        assert ok is False


class TestGenerateOutputPath:
    def test_returns_provided_path_inside_root(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(tmp_path))
        result = generate_output_path(str(tmp_path / "my_output.wav"))
        assert result == str((tmp_path / "my_output.wav").resolve())

    def test_rejects_provided_path_outside_root(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(tmp_path))
        with pytest.raises(ValueError):
            generate_output_path("/tmp/my_output.wav")

    def test_generates_path_when_none(self, tmp_path, monkeypatch):
        import synth_mcp.utils as utils_mod

        monkeypatch.setattr(utils_mod, "SYNTH_OUTPUT_DIR", str(tmp_path))
        result = generate_output_path(None)
        assert result.endswith(".wav")
        assert str(tmp_path) in result

    def test_generated_path_is_in_output_dir(self, tmp_path, monkeypatch):
        import synth_mcp.utils as utils_mod

        monkeypatch.setattr(utils_mod, "SYNTH_OUTPUT_DIR", str(tmp_path))
        result = generate_output_path(None)
        from pathlib import Path

        assert Path(result).parent == tmp_path


class TestConfineOutputPath:
    def _confine(self, path, tmp_path, monkeypatch, suffixes=(".wav",)):
        from synth_mcp.utils import confine_output_path

        monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(tmp_path))
        return confine_output_path(path, suffixes)

    def test_relative_path_lands_in_root(self, tmp_path, monkeypatch):
        out = self._confine("a.wav", tmp_path, monkeypatch)
        assert out == str((tmp_path / "a.wav").resolve())

    def test_rejects_parent_traversal(self, tmp_path, monkeypatch):
        with pytest.raises(ValueError, match="inside"):
            self._confine("../escape.wav", tmp_path, monkeypatch)

    def test_rejects_absolute_path_outside_root(self, tmp_path, monkeypatch):
        with pytest.raises(ValueError, match="inside"):
            self._confine("/etc/cron.d/x.wav", tmp_path, monkeypatch)

    def test_rejects_symlink_escape(self, tmp_path, monkeypatch):
        outside = tmp_path / "outside"
        outside.mkdir()
        root = tmp_path / "root"
        root.mkdir()
        (root / "link").symlink_to(outside)
        with pytest.raises(ValueError, match="inside"):
            self._confine("link/x.wav", root, monkeypatch)

    def test_rejects_wrong_suffix(self, tmp_path, monkeypatch):
        with pytest.raises(ValueError, match="end with"):
            self._confine("notes.sh", tmp_path, monkeypatch)

    def test_rejects_existing_file(self, tmp_path, monkeypatch):
        (tmp_path / "a.wav").write_text("x")
        with pytest.raises(ValueError, match="exists"):
            self._confine("a.wav", tmp_path, monkeypatch)
