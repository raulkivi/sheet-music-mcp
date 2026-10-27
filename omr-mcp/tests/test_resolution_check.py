"""Tests for the Audiveris resolution pre-check (Wave 1 step 8, C3).

Test images are generated with Pillow at the exact pixel size under test, so no
binary fixtures are needed. Engine runners are replaced in ``_ENGINE_RUNNERS`` so
neither oemer nor Audiveris ever runs.
"""

from unittest.mock import MagicMock

import pytest
from PIL import Image

import omr_mcp.omr_engine as eng
from omr_mcp.omr_engine import recognize_image, recognize_image_to_file, recognize_images
from omr_mcp.utils import (
    RESOLUTION_MIN_LONG_SIDE_PX,
    RESOLUTION_RECOMMENDED_LONG_SIDE_PX,
    ResolutionCheck,
    check_resolution,
)

_MUSICXML = '<score-partwise><part id="P1"><measure number="1"/></part></score-partwise>'
_LOW_RES_WARNING = "low resolution; recognition may fail"


def _make_image(tmp_path, width, height, name="sheet.png"):
    path = tmp_path / name
    Image.new("L", (width, height), color=255).save(path)
    return path


def _mock_runner(tmp_path, monkeypatch, engine):
    """Replace *engine*'s runner with a mock that returns a valid MusicXML file."""
    result_path = tmp_path / f"{engine}_out.musicxml"
    result_path.write_text(_MUSICXML)
    runner = MagicMock(return_value=str(result_path))
    monkeypatch.setitem(eng._ENGINE_RUNNERS, engine, runner)
    return runner


# ---------------------------------------------------------------------------
# check_resolution — pure function, thresholds
# ---------------------------------------------------------------------------


class TestCheckResolution:
    def test_threshold_constants(self):
        assert RESOLUTION_MIN_LONG_SIDE_PX == 1500
        assert RESOLUTION_RECOMMENDED_LONG_SIDE_PX == 2500

    @pytest.mark.parametrize(
        "long_side, verdict",
        [(1499, "too_small"), (1500, "low"), (2499, "low"), (2500, "ok")],
    )
    @pytest.mark.parametrize("orientation", ["portrait", "landscape"])
    def test_verdict_at_boundaries(self, tmp_path, long_side, verdict, orientation):
        short_side = 400
        size = (short_side, long_side) if orientation == "portrait" else (long_side, short_side)
        path = _make_image(tmp_path, *size)

        check = check_resolution(str(path))

        assert isinstance(check, ResolutionCheck)
        assert check.long_side_px == long_side
        assert check.verdict == verdict

    def test_ok_has_no_message(self, tmp_path):
        check = check_resolution(str(_make_image(tmp_path, 2480, 3508)))
        assert check.verdict == "ok"
        assert check.message is None

    def test_low_message_mentions_resolution(self, tmp_path):
        check = check_resolution(str(_make_image(tmp_path, 1200, 2000)))
        assert check.message == _LOW_RES_WARNING

    def test_too_small_message_names_pixel_size(self, tmp_path):
        check = check_resolution(str(_make_image(tmp_path, 700, 1000)))
        assert "1000" in check.message

    def test_accepts_path_object(self, tmp_path):
        check = check_resolution(_make_image(tmp_path, 3000, 2000))
        assert check.long_side_px == 3000


# ---------------------------------------------------------------------------
# recognize_image
# ---------------------------------------------------------------------------


class TestRecognizeImagePrecheck:
    def test_audiveris_too_small_fails_without_running(self, tmp_path, monkeypatch):
        runner = _mock_runner(tmp_path, monkeypatch, "audiveris")
        image = _make_image(tmp_path, 700, 1000)

        result = recognize_image(str(image), engine="audiveris")

        assert result["error_code"] == "INVALID_INPUT"
        assert "1000" in result["error"]
        assert "300 DPI" in result["hint"]
        assert "2500 px" in result["hint"]
        runner.assert_not_called()

    def test_audiveris_low_resolution_runs_with_warning(self, tmp_path, monkeypatch):
        runner = _mock_runner(tmp_path, monkeypatch, "audiveris")
        image = _make_image(tmp_path, 1400, 2000)

        result = recognize_image(str(image), engine="audiveris")

        runner.assert_called_once_with(str(image))
        assert "error" not in result
        assert result["musicxml"] == _MUSICXML
        assert result["warnings"] == [_LOW_RES_WARNING]

    def test_audiveris_adequate_resolution_has_no_warnings_key(self, tmp_path, monkeypatch):
        runner = _mock_runner(tmp_path, monkeypatch, "audiveris")
        image = _make_image(tmp_path, 2480, 3508)

        result = recognize_image(str(image), engine="audiveris")

        runner.assert_called_once()
        assert "warnings" not in result

    def test_oemer_not_checked(self, tmp_path, monkeypatch):
        runner = _mock_runner(tmp_path, monkeypatch, "oemer")
        image = _make_image(tmp_path, 700, 1000)

        result = recognize_image(str(image), engine="oemer")

        runner.assert_called_once_with(str(image))
        assert "error" not in result
        assert "warnings" not in result

    def test_oemer_default_engine_not_checked(self, tmp_path, monkeypatch):
        runner = _mock_runner(tmp_path, monkeypatch, "oemer")
        image = _make_image(tmp_path, 700, 1000)

        result = recognize_image(str(image))

        runner.assert_called_once()
        assert "warnings" not in result

    def test_audiveris_unreadable_image_skips_check(self, tmp_path, monkeypatch):
        # Pillow can't read it, so the pre-check stays out of the way and the
        # engine reports the problem as before.
        runner = _mock_runner(tmp_path, monkeypatch, "audiveris")
        image = tmp_path / "broken.png"
        image.write_bytes(b"not really a png")

        result = recognize_image(str(image), engine="audiveris")

        runner.assert_called_once()
        assert "warnings" not in result


# ---------------------------------------------------------------------------
# recognize_image_to_file
# ---------------------------------------------------------------------------


class TestRecognizeImageToFilePrecheck:
    def test_audiveris_too_small_fails_without_running(self, tmp_path, monkeypatch):
        runner = _mock_runner(tmp_path, monkeypatch, "audiveris")
        image = _make_image(tmp_path, 1000, 700)

        result = recognize_image_to_file(str(image), engine="audiveris")

        assert result["error_code"] == "INVALID_INPUT"
        assert "hint" in result
        runner.assert_not_called()
        assert not image.with_suffix(".musicxml").exists()

    def test_audiveris_low_resolution_runs_with_warning(self, tmp_path, monkeypatch):
        runner = _mock_runner(tmp_path, monkeypatch, "audiveris")
        image = _make_image(tmp_path, 2000, 1400)

        result = recognize_image_to_file(str(image), engine="audiveris")

        runner.assert_called_once()
        assert result["output_path"] == str(image.with_suffix(".musicxml"))
        assert result["warnings"] == [_LOW_RES_WARNING]

    def test_oemer_not_checked(self, tmp_path, monkeypatch):
        runner = _mock_runner(tmp_path, monkeypatch, "oemer")
        image = _make_image(tmp_path, 1000, 700)

        result = recognize_image_to_file(str(image), engine="oemer")

        runner.assert_called_once()
        assert "error" not in result
        assert "warnings" not in result


# ---------------------------------------------------------------------------
# recognize_images (multi-page)
# ---------------------------------------------------------------------------


class TestRecognizeImagesPrecheck:
    def test_audiveris_fails_fast_naming_the_small_page(self, tmp_path, monkeypatch):
        runner = _mock_runner(tmp_path, monkeypatch, "audiveris")
        page1 = _make_image(tmp_path, 2480, 3508, "p1.png")
        page2 = _make_image(tmp_path, 700, 1000, "p2.png")

        result = recognize_images([str(page1), str(page2)], engine="audiveris")

        assert result["error_code"] == "INVALID_INPUT"
        assert "Page 2" in result["error"]
        assert "p2.png" in result["error"]
        assert "hint" in result
        # Fail fast: page 1 is fine but must not be recognized either.
        runner.assert_not_called()

    def test_audiveris_low_resolution_page_warning_names_page(self, tmp_path, monkeypatch):
        runner = _mock_runner(tmp_path, monkeypatch, "audiveris")
        page1 = _make_image(tmp_path, 2480, 3508, "p1.png")
        page2 = _make_image(tmp_path, 1400, 2000, "p2.png")

        result = recognize_images([str(page1), str(page2)], engine="audiveris")

        assert runner.call_count == 2
        assert "error" not in result
        assert result["metadata"]["page_count"] == 2
        assert result["warnings"] == [f"Page 2: {_LOW_RES_WARNING}"]

    def test_audiveris_single_low_page_keeps_warning(self, tmp_path, monkeypatch):
        _mock_runner(tmp_path, monkeypatch, "audiveris")
        page = _make_image(tmp_path, 1400, 2000, "p1.png")

        result = recognize_images([str(page)], engine="audiveris")

        assert result["metadata"]["page_count"] == 1
        assert result["warnings"] == [f"Page 1: {_LOW_RES_WARNING}"]

    def test_audiveris_all_adequate_has_no_warnings_key(self, tmp_path, monkeypatch):
        _mock_runner(tmp_path, monkeypatch, "audiveris")
        page1 = _make_image(tmp_path, 2480, 3508, "p1.png")
        page2 = _make_image(tmp_path, 3508, 2480, "p2.png")

        result = recognize_images([str(page1), str(page2)], engine="audiveris")

        assert "error" not in result
        assert "warnings" not in result

    def test_oemer_not_checked(self, tmp_path, monkeypatch):
        runner = _mock_runner(tmp_path, monkeypatch, "oemer")
        page1 = _make_image(tmp_path, 700, 1000, "p1.png")
        page2 = _make_image(tmp_path, 700, 1000, "p2.png")

        result = recognize_images([str(page1), str(page2)], engine="oemer")

        assert runner.call_count == 2
        assert "error" not in result
        assert "warnings" not in result
