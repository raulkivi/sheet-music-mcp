"""Tests for OMR engine module."""

import subprocess
import zipfile
import pytest
from pathlib import Path
from unittest.mock import patch

from omr_mcp.omr_engine import (
    recognize_image,
    recognize_image_to_file,
    recognize_images,
    _extract_musicxml_metadata,
    _merge_musicxml_pages,
    health_check,
)


class TestExtractMusicxmlMetadata:
    """Tests for MusicXML metadata extraction."""

    def test_extract_staves(self):
        musicxml = '''<?xml version="1.0"?>
        <score-partwise>
            <part-list>
                <score-part id="P1"><part-name>Soprano</part-name></score-part>
                <score-part id="P2"><part-name>Alto</part-name></score-part>
            </part-list>
            <part id="P1">
                <measure number="1"></measure>
                <measure number="2"></measure>
            </part>
            <part id="P2">
                <measure number="1"></measure>
                <measure number="2"></measure>
            </part>
        </score-partwise>'''
        
        metadata = _extract_musicxml_metadata(musicxml)
        assert metadata["staves_detected"] == 2
        assert metadata["measures"] == 2

    def test_extract_empty_musicxml(self):
        musicxml = '<?xml version="1.0"?><score-partwise></score-partwise>'

        metadata = _extract_musicxml_metadata(musicxml)
        assert metadata["staves_detected"] == 0
        assert metadata["measures"] == 0

    def test_extract_measures_zero_indexed(self):
        # Audiveris numbers measures starting at 0, not 1 (unlike oemer) — measure count
        # must come from counting distinct numbers, not max(), or it undercounts by one.
        musicxml = '''<?xml version="1.0"?>
        <score-partwise>
            <part id="P1">
                <measure number="0"></measure>
                <measure number="1"></measure>
                <measure number="2"></measure>
            </part>
        </score-partwise>'''

        metadata = _extract_musicxml_metadata(musicxml)
        assert metadata["measures"] == 3


class TestRecognizeImage:
    """Tests for recognize_image function."""

    def test_nonexistent_file(self):
        result = recognize_image("/nonexistent/path/image.png")
        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_unsupported_format(self, tmp_path):
        test_file = tmp_path / "test.bmp"
        test_file.write_bytes(b"fake content")
        
        result = recognize_image(str(test_file))
        assert "error" in result
        assert "Unsupported format" in result["error"]


class TestMergeMusicxmlPages:
    """Tests for internal MusicXML page merger."""

    SIMPLE_PAGE = '''<?xml version="1.0"?>
    <score-partwise>
        <part-list><score-part id="P1"><part-name>Soprano</part-name></score-part></part-list>
        <part id="P1">
            <measure number="1"></measure>
            <measure number="2"></measure>
        </part>
    </score-partwise>'''

    def test_single_page_returned_unchanged(self):
        result = _merge_musicxml_pages([self.SIMPLE_PAGE])
        assert result == self.SIMPLE_PAGE

    def test_two_pages_doubles_measure_count(self):
        import xml.etree.ElementTree as ET
        result = _merge_musicxml_pages([self.SIMPLE_PAGE, self.SIMPLE_PAGE])
        root = ET.fromstring(result)
        measures = root.find("part").findall("measure")
        assert len(measures) == 4

    def test_measure_numbers_renumbered(self):
        import xml.etree.ElementTree as ET
        result = _merge_musicxml_pages([self.SIMPLE_PAGE, self.SIMPLE_PAGE])
        root = ET.fromstring(result)
        numbers = [int(m.get("number")) for m in root.find("part").findall("measure")]
        assert numbers == [1, 2, 3, 4]


class TestRecognizeImages:
    """Tests for the batch recognize_images function."""

    def test_empty_list_returns_error(self):
        result = recognize_images([])
        assert "error" in result
        assert result.get("error_code") == "INVALID_PARAMETER"

    def test_nonexistent_file_returns_error(self):
        result = recognize_images(["/nonexistent/page1.png"])
        assert "error" in result

    def test_multiple_nonexistent_files_returns_error(self):
        result = recognize_images(["/no/page1.png", "/no/page2.png"])
        assert "error" in result


class TestHealthCheck:
    """Tests for the health_check function."""

    def test_returns_status_field(self):
        result = health_check()
        assert "status" in result
        assert result["status"] in ("ok", "degraded")

    def test_returns_checks_dict(self):
        result = health_check()
        assert "checks" in result
        assert isinstance(result["checks"], dict)

    def test_checks_include_oemer(self):
        result = health_check()
        assert "oemer" in result["checks"]
        assert result["checks"]["oemer"]["status"] in ("ok", "missing")

    def test_checks_include_model_cache(self):
        result = health_check()
        assert "model_cache" in result["checks"]
        assert result["checks"]["model_cache"]["status"] in ("ok", "missing")

    def test_overall_ok_when_all_checks_ok(self, tmp_path, monkeypatch):
        """status == 'ok' when oemer is importable and checkpoint file exists."""
        import omr_mcp.omr_engine as eng

        # Pretend oemer is installed
        fake_oemer = type("FakeOemer", (), {})()
        import sys
        monkeypatch.setitem(sys.modules, "oemer", fake_oemer)

        # Point the checkpoint path at a file that exists
        checkpoint = tmp_path / "model.onnx"
        checkpoint.write_bytes(b"fake checkpoint")
        monkeypatch.setattr(eng, "_oemer_checkpoint_path", lambda: checkpoint)

        result = health_check()
        assert result["status"] == "ok"

    def test_degraded_when_cache_missing(self, monkeypatch):
        """status == 'degraded' when model checkpoint file does not exist."""
        import omr_mcp.omr_engine as eng
        from pathlib import Path
        import sys

        # Pretend oemer is installed
        fake_oemer = type("FakeOemer", (), {})()
        monkeypatch.setitem(sys.modules, "oemer", fake_oemer)

        # Point the checkpoint path at a non-existent file
        monkeypatch.setattr(
            eng, "_oemer_checkpoint_path", lambda: Path("/nonexistent/oemer_cache/model.onnx")
        )

        result = health_check()
        assert result["status"] == "degraded"
        assert result["checks"]["model_cache"]["status"] == "missing"
        assert result["checks"]["model_cache"]["path"] is None

    def test_model_cache_note_present(self, monkeypatch):
        """Missing cache includes a helpful note about first-run download."""
        import omr_mcp.omr_engine as eng
        from pathlib import Path
        import sys

        fake_oemer = type("FakeOemer", (), {})()
        monkeypatch.setitem(sys.modules, "oemer", fake_oemer)
        monkeypatch.setattr(
            eng, "_oemer_checkpoint_path", lambda: Path("/nonexistent/oemer_cache/model.onnx")
        )

        result = health_check()
        note = result["checks"]["model_cache"]["note"]
        assert "100 MB" in note or "download" in note.lower()

    def test_checks_include_audiveris(self):
        result = health_check()
        assert "audiveris" in result["checks"]
        assert result["checks"]["audiveris"]["status"] in ("ok", "not_installed")

    def test_audiveris_not_installed_does_not_degrade_overall_status(self, tmp_path, monkeypatch):
        """audiveris is an optional alternate engine — its absence must not flip the
        overall server status to 'degraded' the way a missing oemer/model_cache would."""
        import omr_mcp.omr_engine as eng
        import sys

        fake_oemer = type("FakeOemer", (), {})()
        monkeypatch.setitem(sys.modules, "oemer", fake_oemer)
        checkpoint = tmp_path / "model.onnx"
        checkpoint.write_bytes(b"fake checkpoint")
        monkeypatch.setattr(eng, "_oemer_checkpoint_path", lambda: checkpoint)
        monkeypatch.setattr(eng, "_audiveris_binary_path", lambda: tmp_path / "nonexistent" / "Audiveris")

        result = health_check()
        assert result["checks"]["audiveris"]["status"] == "not_installed"
        assert result["status"] == "ok"


class TestRecognizeImageToFile:
    """Tests for recognize_image_to_file function."""

    def test_nonexistent_file(self):
        result = recognize_image_to_file("/nonexistent/path/image.png")
        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_unsupported_format(self, tmp_path):
        test_file = tmp_path / "test.gif"
        test_file.write_bytes(b"fake content")
        
        result = recognize_image_to_file(str(test_file))
        assert "error" in result
        assert "Unsupported format" in result["error"]

    def test_auto_generated_output_path(self, tmp_path, monkeypatch):
        """Test that output path is auto-generated when not specified."""
        # We can't test actual OMR without oemer, but we can check the logic
        test_file = tmp_path / "test.png"
        test_file.write_bytes(b"fake png content")

        # The function will fail because it's not a real PNG,
        # but we're testing the error handling and path logic
        result = recognize_image_to_file(str(test_file))
        # Will get an error from oemer, but the function should handle it
        assert "error" in result or "output_path" in result


class TestEngineSelection:
    """Tests for the engine= parameter (oemer vs. audiveris) on recognize_image /
    recognize_image_to_file — dispatch and validation, not real engine invocation."""

    def test_unknown_engine_returns_invalid_parameter(self, tmp_path):
        test_file = tmp_path / "test.png"
        test_file.write_bytes(b"fake png content")

        result = recognize_image(str(test_file), engine="not-a-real-engine")
        assert result["error_code"] == "INVALID_PARAMETER"
        assert "not-a-real-engine" in result["error"]

    def test_unknown_engine_returns_invalid_parameter_to_file(self, tmp_path):
        test_file = tmp_path / "test.png"
        test_file.write_bytes(b"fake png content")

        result = recognize_image_to_file(str(test_file), engine="not-a-real-engine")
        assert result["error_code"] == "INVALID_PARAMETER"

    def test_default_engine_is_oemer_in_metadata(self, tmp_path, monkeypatch):
        import omr_mcp.omr_engine as eng

        test_file = tmp_path / "test.png"
        test_file.write_bytes(b"fake png content")

        result_path = tmp_path / "out.musicxml"
        result_path.write_text('<score-partwise><part id="P1"><measure number="1"/></part></score-partwise>')
        monkeypatch.setitem(eng._ENGINE_RUNNERS, "oemer", lambda p: str(result_path))

        result = recognize_image(str(test_file))
        assert result["metadata"]["engine"] == "oemer"

    def test_explicit_audiveris_engine_used(self, tmp_path, monkeypatch):
        import omr_mcp.omr_engine as eng

        test_file = tmp_path / "test.png"
        test_file.write_bytes(b"fake png content")

        result_path = tmp_path / "out.musicxml"
        result_path.write_text(
            '<score-partwise>'
            '<part id="P1"><measure number="0"/></part>'
            '<part id="P2"><measure number="0"/></part>'
            '</score-partwise>'
        )
        monkeypatch.setitem(eng._ENGINE_RUNNERS, "audiveris", lambda p: str(result_path))

        result = recognize_image(str(test_file), engine="audiveris")
        assert result["metadata"]["engine"] == "audiveris"
        assert result["metadata"]["staves_detected"] == 2


class TestAudiverisEngine:
    """Tests for the Audiveris subprocess wrapper (_ensure_audiveris_installed,
    _run_audiveris). All external calls (network, subprocess) are mocked — these never
    invoke a real Audiveris binary."""

    _MINIMAL_MUSICXML = (
        '<?xml version="1.0"?><score-partwise>'
        '<part id="P1"><measure number="0"></measure></part>'
        '</score-partwise>'
    )

    def test_ensure_installed_skips_download_if_binary_exists(self, tmp_path, monkeypatch):
        import omr_mcp.omr_engine as eng

        fake_binary = tmp_path / "Audiveris"
        fake_binary.write_bytes(b"fake")
        monkeypatch.setattr(eng, "_audiveris_binary_path", lambda: fake_binary)

        def _fail_if_called(*a, **kw):
            raise AssertionError("should not attempt to download when binary already exists")
        monkeypatch.setattr(eng.urllib.request, "urlretrieve", _fail_if_called)

        result = eng._ensure_audiveris_installed()
        assert result == fake_binary

    def test_ensure_installed_downloads_and_extracts_when_missing(self, tmp_path, monkeypatch):
        import omr_mcp.omr_engine as eng

        home = tmp_path / "audiveris_home"
        fake_binary = home / "opt" / "audiveris" / "bin" / "Audiveris"

        monkeypatch.setattr(eng, "_audiveris_home", lambda: home)
        # Binary doesn't exist until "extraction" (simulated below) creates it.
        monkeypatch.setattr(eng, "_audiveris_binary_path", lambda: fake_binary)

        downloaded = {}

        def _fake_urlretrieve(url, dest):
            downloaded["url"] = url
            Path(dest).write_bytes(b"fake deb")

        def _fake_run(cmd, check, capture_output, text):
            assert cmd[0] == "dpkg-deb"
            fake_binary.parent.mkdir(parents=True, exist_ok=True)
            fake_binary.write_bytes(b"fake extracted binary")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(eng.urllib.request, "urlretrieve", _fake_urlretrieve)
        monkeypatch.setattr(eng.subprocess, "run", _fake_run)

        result = eng._ensure_audiveris_installed()
        assert result == fake_binary
        assert fake_binary.exists()
        assert downloaded["url"] == eng._AUDIVERIS_DEB_URL
        # The downloaded .deb is cleaned up after extraction.
        assert not (home / "audiveris.deb").exists()

    def test_run_audiveris_extracts_musicxml_from_exported_mxl(self, tmp_path, monkeypatch):
        import omr_mcp.omr_engine as eng

        fake_binary = tmp_path / "Audiveris"
        fake_binary.write_bytes(b"fake")
        monkeypatch.setattr(eng, "_ensure_audiveris_installed", lambda: fake_binary)

        image_path = tmp_path / "score.png"
        image_path.write_bytes(b"fake image")

        def _fake_run(cmd, capture_output, text, timeout):
            output_dir = Path(cmd[cmd.index("-output") + 1])
            stem = Path(cmd[-1]).stem
            with zipfile.ZipFile(output_dir / f"{stem}.mxl", "w") as z:
                z.writestr(f"{stem}.xml", self._MINIMAL_MUSICXML)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(eng.subprocess, "run", _fake_run)

        result_path = eng._run_audiveris(str(image_path))
        assert Path(result_path).read_text() == self._MINIMAL_MUSICXML

    def test_run_audiveris_raises_when_no_output_produced(self, tmp_path, monkeypatch):
        """Audiveris can exit 0 while rejecting every sheet (e.g. resolution too low) —
        must be detected by output-file absence, not exit code."""
        import omr_mcp.omr_engine as eng

        fake_binary = tmp_path / "Audiveris"
        fake_binary.write_bytes(b"fake")
        monkeypatch.setattr(eng, "_ensure_audiveris_installed", lambda: fake_binary)

        image_path = tmp_path / "score.png"
        image_path.write_bytes(b"fake image")

        def _fake_run(cmd, capture_output, text, timeout):
            return subprocess.CompletedProcess(cmd, 0, stdout="sheet rejected: low resolution", stderr="")

        monkeypatch.setattr(eng.subprocess, "run", _fake_run)

        with pytest.raises(RuntimeError, match="resolution"):
            eng._run_audiveris(str(image_path))

    def test_recognize_image_audiveris_low_resolution_maps_to_processing_failed(self, tmp_path, monkeypatch):
        import omr_mcp.omr_engine as eng

        fake_binary = tmp_path / "Audiveris"
        fake_binary.write_bytes(b"fake")
        monkeypatch.setattr(eng, "_ensure_audiveris_installed", lambda: fake_binary)

        def _fake_run(cmd, capture_output, text, timeout):
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        monkeypatch.setattr(eng.subprocess, "run", _fake_run)

        image_path = tmp_path / "score.png"
        image_path.write_bytes(b"fake image")

        result = recognize_image(str(image_path), engine="audiveris")
        assert result["error_code"] == "PROCESSING_FAILED"
        assert "resolution" in result["error"].lower()


class TestRunOemer:
    """oemer's model must be made loadable before each recognition."""

    def test_model_is_fixed_after_download_and_before_inference(self, tmp_path):
        from omr_mcp import omr_engine

        model = tmp_path / "unet_big" / "model.onnx"
        calls = []
        with patch.object(omr_engine, "_ensure_oemer_checkpoints", side_effect=lambda: calls.append("download")), \
             patch.object(omr_engine, "_oemer_checkpoint_path", return_value=model), \
             patch.object(omr_engine, "fix_negative_convtranspose_pads",
                          side_effect=lambda path: calls.append(("fix", path))), \
             patch("oemer.ete.clear_data"), \
             patch("oemer.ete.extract", side_effect=lambda args: calls.append("extract") or "out.musicxml"):
            assert omr_engine._run_oemer("page.png") == "out.musicxml"
        assert calls == ["download", ("fix", model), "extract"]
