"""Measure ranges on the render tools (docs/conventions.md, Measure Ranges; UX Wave 3, B2).

``measures=[start, end]`` cuts the score with ``sheet_music_mcp_core.measures.select_measures``
once, before backend dispatch, so MuseScore and Verovio receive the same cut score. The backends
are replaced by spies and their input is inspected with ``describe_score``.
"""

import json
from unittest.mock import patch

import pytest
from sheet_music_mcp_core.measures import MEASURES_PROPERTY
from sheet_music_mcp_core.scores import describe_score

from render_mcp.engine import ProcessingError, render_to_image, render_to_pdf
from render_mcp.server import call_tool, list_tools

RENDER_TOOLS = ("render_to_pdf", "render_to_image")
RANGE_HINT = "This score has measures 1–6."

# One whole note per bar, a different pitch in each, so a kept bar is recognisable.
_STEPS = ("C", "D", "E", "F", "G", "A")


def _part(part_id: str, octave: int) -> str:
    measures = []
    for number, step in enumerate(_STEPS, start=1):
        attributes = (
            "<attributes><divisions>1</divisions><key><fifths>0</fifths></key>"
            "<time><beats>4</beats><beat-type>4</beat-type></time>"
            "<clef><sign>G</sign><line>2</line></clef></attributes>"
            if number == 1
            else ""
        )
        measures.append(
            f'<measure number="{number}">{attributes}'
            f"<note><pitch><step>{step}</step><octave>{octave}</octave></pitch>"
            "<duration>4</duration><type>whole</type></note></measure>"
        )
    return f'<part id="{part_id}">{"".join(measures)}</part>'


SIX_BARS = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<score-partwise version="3.1"><part-list>'
    '<score-part id="P1"><part-name>Soprano</part-name></score-part>'
    '<score-part id="P2"><part-name>Alto</part-name></score-part>'
    f'</part-list>{_part("P1", 5)}{_part("P2", 4)}</score-partwise>'
)


@pytest.fixture
def root(tmp_path, monkeypatch):
    """The output root, so the tools accept an explicit output_path inside it."""
    monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(tmp_path))
    monkeypatch.delenv("SHEET_MUSIC_INPUT_ROOTS", raising=False)
    return tmp_path


@pytest.fixture(params=["verovio", "musescore"])
def backend(request):
    """Force one backend; yields its name (the suffix of its private render functions)."""
    command = "mscore4" if request.param == "musescore" else None
    with (
        patch("render_mcp.engine._MUSESCORE_CMD", command),
        patch("render_mcp.engine._VEROVIO_AVAILABLE", True),
    ):
        yield request.param


def _pdf_spy(backend: str):
    """Patch the backend's PDF renderer with a spy that returns a one-page result."""
    return patch(
        f"render_mcp.engine._render_pdf_{backend}",
        side_effect=lambda text, path: (path, 1),
    )


def _image_spy(backend: str):
    """Patch the backend's image renderer with a spy that returns minimal metadata."""
    return patch(
        f"render_mcp.engine._render_image_{backend}",
        side_effect=lambda text, page, fmt, dpi, path: {
            "image_path": path, "format": fmt, "page": page, "total_pages": 1, "backend": backend,
        },
    )


def _soprano_range(text: str) -> list[str]:
    """The lowest and highest soprano pitch of a score the backend received."""
    summary = describe_score(text)
    soprano = next(part for part in summary["parts"] if part["id"] == "P1")
    return [soprano["range"]["low"], soprano["range"]["high"]]


# ---------------------------------------------------------------------------
# Engine: the backend receives only the selected bars
# ---------------------------------------------------------------------------


class TestEngineCut:
    def test_pdf_backend_gets_only_bars_3_and_4(self, backend, tmp_path):
        with _pdf_spy(backend) as spy:
            render_to_pdf(SIX_BARS, str(tmp_path / "out.pdf"), measures=[3, 4])

        sent = spy.call_args.args[0]
        summary = describe_score(sent)
        assert summary["measures"] == 2
        assert [part["id"] for part in summary["parts"]] == ["P1", "P2"]
        assert _soprano_range(sent) == ["E5", "F5"]
        assert summary["time"] == "4/4"

    def test_image_backend_gets_only_bars_3_and_4(self, backend, tmp_path):
        with _image_spy(backend) as spy:
            render_to_image(SIX_BARS, 1, "png", 150, str(tmp_path / "out.png"), measures=[3, 4])

        sent = spy.call_args.args[0]
        assert describe_score(sent)["measures"] == 2
        assert _soprano_range(sent) == ["E5", "F5"]

    def test_tuple_range_is_accepted(self, tmp_path):
        with (
            patch("render_mcp.engine._MUSESCORE_CMD", None),
            patch("render_mcp.engine._VEROVIO_AVAILABLE", True),
            _pdf_spy("verovio") as spy,
        ):
            render_to_pdf(SIX_BARS, str(tmp_path / "out.pdf"), measures=(6, 6))

        assert describe_score(spy.call_args.args[0])["measures"] == 1

    @pytest.mark.parametrize("kwargs", [{}, {"measures": None}], ids=["omitted", "none"])
    def test_default_passes_the_score_unchanged(self, kwargs, backend, tmp_path):
        with _pdf_spy(backend) as pdf_spy, _image_spy(backend) as image_spy:
            render_to_pdf(SIX_BARS, str(tmp_path / "out.pdf"), **kwargs)
            render_to_image(SIX_BARS, 1, "svg", 150, str(tmp_path / "out.svg"), **kwargs)

        assert pdf_spy.call_args.args[0] is SIX_BARS
        assert image_spy.call_args.args[0] is SIX_BARS

    @pytest.mark.parametrize("measures", [[5, 99], [0, 2], [4, 3]])
    def test_out_of_range_or_reversed_is_invalid_parameter(self, measures, tmp_path):
        with (
            patch("render_mcp.engine._MUSESCORE_CMD", None),
            patch("render_mcp.engine._VEROVIO_AVAILABLE", True),
            _pdf_spy("verovio") as spy,
            pytest.raises(ProcessingError) as excinfo,
        ):
            render_to_pdf(SIX_BARS, str(tmp_path / "out.pdf"), measures=measures)

        assert excinfo.value.error_code == "INVALID_PARAMETER"
        assert excinfo.value.hint == RANGE_HINT
        spy.assert_not_called()


# ---------------------------------------------------------------------------
# Server: schema and the tool path end to end (backend spied)
# ---------------------------------------------------------------------------


class TestServer:
    @pytest.mark.parametrize("name", RENDER_TOOLS)
    async def test_schema_lists_measures(self, name):
        tool = next(t for t in await list_tools() if t.name == name)

        assert tool.input_schema["properties"]["measures"] == MEASURES_PROPERTY["measures"]
        assert "measures" not in tool.input_schema.get("required", [])

    async def test_render_to_pdf_cuts_before_the_backend(self, root):
        with (
            patch("render_mcp.engine._MUSESCORE_CMD", None),
            patch("render_mcp.engine._VEROVIO_AVAILABLE", True),
            _pdf_spy("verovio") as spy,
        ):
            result = await call_tool(
                "render_to_pdf",
                {"musicxml": SIX_BARS, "output_path": str(root / "cut.pdf"), "measures": [3, 4]},
            )

        assert "error" not in json.loads(result[0].text)
        assert describe_score(spy.call_args.args[0])["measures"] == 2

    async def test_render_to_image_cuts_before_the_backend(self, root):
        with (
            patch("render_mcp.engine._MUSESCORE_CMD", None),
            patch("render_mcp.engine._VEROVIO_AVAILABLE", True),
            _image_spy("verovio") as spy,
        ):
            result = await call_tool(
                "render_to_image",
                {"musicxml": SIX_BARS, "output_path": str(root / "cut.png"), "measures": [3, 4]},
            )

        assert "error" not in json.loads(result[0].text)
        assert describe_score(spy.call_args.args[0])["measures"] == 2

    @pytest.mark.parametrize("name", RENDER_TOOLS)
    @pytest.mark.parametrize("measures", [[5, 99], [4, 3]])
    async def test_bad_range_is_invalid_parameter_with_hint(self, name, measures, root):
        result = await call_tool(name, {"musicxml": SIX_BARS, "measures": measures})

        data = json.loads(result[0].text)
        assert data["error_code"] == "INVALID_PARAMETER"
        assert data["hint"] == RANGE_HINT

    async def test_list_capabilities_lists_measures(self):
        data = json.loads((await call_tool("list_capabilities", {}))[0].text)

        assert "measures" in data["input_parameters"]


# ---------------------------------------------------------------------------
# A real Verovio render of a cut score
# ---------------------------------------------------------------------------


class TestRealRender:
    def test_verovio_renders_a_cut_score_to_svg(self, tmp_path):
        out = tmp_path / "cut.svg"
        with patch("render_mcp.engine._MUSESCORE_CMD", None):
            result = render_to_image(SIX_BARS, 1, "svg", 150, str(out), measures=[3, 4])

        assert result["total_pages"] == 1
        svg = out.read_text(encoding="utf-8")
        assert svg.count('class="measure"') == 2
