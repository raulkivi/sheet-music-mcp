"""Server-side page SVG for the Score Viewer's fallback renderer (engine layer, no MCP).

The viewer renders with Verovio WASM where the host allows WebAssembly and calls
``render_page_svg`` where it does not, so both paths must lay a page out the same way.
"""

import json
from pathlib import Path

import pytest
import verovio

from render_mcp.engine import ProcessingError, SvgPageRenderer, page_layout

from .test_server import VALID_MUSICXML

LAYOUT_CASES = Path(__file__).parents[2] / "ui" / "packages" / "kit" / "src" / "score" / "layout-cases.json"

_MEASURE = """\
    <measure number="{n}">{attributes}
      <note><pitch><step>C</step><octave>5</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>D</step><octave>5</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>E</step><octave>5</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>F</step><octave>5</octave></pitch><duration>1</duration><type>quarter</type></note>
    </measure>"""
_ATTRIBUTES = """
      <attributes><divisions>1</divisions><key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time><clef><sign>G</sign><line>2</line></clef></attributes>"""


def long_score(measures: int = 160) -> str:
    """A one-part score long enough to need several pages."""
    body = "\n".join(
        _MEASURE.format(n=n, attributes=_ATTRIBUTES if n == 1 else "") for n in range(1, measures + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<score-partwise version="3.1">\n'
        '  <part-list><score-part id="P1"><part-name>Soprano</part-name></score-part></part-list>\n'
        f'  <part id="P1">\n{body}\n  </part>\n</score-partwise>'
    )


class CountingToolkit:
    """A real Verovio toolkit that records loads, option changes and re-layouts."""

    instances: list["CountingToolkit"] = []

    def __init__(self):
        self._tk = verovio.toolkit()
        self.loads = 0
        self.relayouts = 0
        self.options: list[dict] = []
        CountingToolkit.instances.append(self)

    def setOptions(self, options):
        self.options.append(dict(options))
        return self._tk.setOptions(options)

    def loadData(self, data):
        self.loads += 1
        return self._tk.loadData(data)

    def redoLayout(self, *args):
        self.relayouts += 1
        return self._tk.redoLayout(*args)

    def __getattr__(self, name):
        return getattr(self._tk, name)


class RejectingToolkit(CountingToolkit):
    """Verovio reads almost any text; this one refuses the score marked UNREADABLE."""

    def loadData(self, data):
        return False if "UNREADABLE" in data else super().loadData(data)


UNREADABLE = "<score-partwise><!-- UNREADABLE --></score-partwise>"


@pytest.fixture
def counting():
    CountingToolkit.instances = []
    return SvgPageRenderer(toolkit_factory=CountingToolkit)


class TestLayout:
    def test_matches_the_ui_layout_cases(self):
        if not LAYOUT_CASES.is_file():
            pytest.skip("ui/ workspace not present")
        cases = json.loads(LAYOUT_CASES.read_text(encoding="utf-8"))["cases"]

        for case in cases:
            assert page_layout(case["containerWidth"], case["zoom"]) == case["layout"], case

    def test_rounds_halves_up_like_javascript(self):
        # Math.round(0.5) is 1 in JS; Python's round() would give 0 (banker's rounding).
        assert page_layout(1000, 0.6125)["scale"] == 25


class TestRender:
    def test_renders_one_page_as_svg(self):
        result = SvgPageRenderer().render(VALID_MUSICXML, page=1, width_px=1000, zoom=1)

        assert set(result) == {"svg", "page", "page_count"}
        assert result["svg"].lstrip().startswith("<svg")
        assert (result["page"], result["page_count"]) == (1, 1)

    def test_uses_the_viewer_layout_options(self, counting):
        counting.render(VALID_MUSICXML, page=1, width_px=900, zoom=1.25)

        options = CountingToolkit.instances[0].options[-1]
        assert {k: options[k] for k in ("scale", "pageWidth", "pageHeight")} == page_layout(900, 1.25)
        assert options["adjustPageHeight"] is True
        assert options["breaks"] == "auto"
        assert options["footer"] == "none"

    def test_pages_through_a_long_score(self):
        renderer = SvgPageRenderer()

        first = renderer.render(long_score(), page=1, width_px=1000, zoom=1)
        last = renderer.render(long_score(), page=first["page_count"], width_px=1000, zoom=1)

        assert first["page_count"] > 1
        assert last["page"] == first["page_count"]
        assert last["svg"] != first["svg"]

    def test_narrower_or_zoomed_layouts_need_more_pages(self):
        renderer = SvgPageRenderer()
        score = long_score()

        wide = renderer.render(score, page=1, width_px=1600, zoom=1)["page_count"]
        narrow = renderer.render(score, page=1, width_px=500, zoom=1)["page_count"]
        zoomed = renderer.render(score, page=1, width_px=1600, zoom=2)["page_count"]

        assert narrow > wide
        assert zoomed > wide

    def test_page_out_of_range_names_the_range(self):
        with pytest.raises(ProcessingError) as caught:
            SvgPageRenderer().render(VALID_MUSICXML, page=3, width_px=1000, zoom=1)

        error = caught.value
        assert error.error_code == "INVALID_PARAMETER"
        assert "Page 3" in str(error)
        assert error.hint == "This score has pages 1–1 at this width and zoom."

    def test_unreadable_score_is_invalid_input(self):
        with pytest.raises(ProcessingError) as caught:
            SvgPageRenderer(RejectingToolkit).render(UNREADABLE, page=1, width_px=1000, zoom=1)

        assert caught.value.error_code == "INVALID_INPUT"


class TestCache:
    def test_paging_the_same_score_parses_it_once(self, counting):
        score = long_score()

        for page in (1, 2, 1):
            counting.render(score, page=page, width_px=1000, zoom=1)

        [toolkit] = CountingToolkit.instances
        assert toolkit.loads == 1
        assert toolkit.relayouts == 0

    def test_a_new_layout_reflows_without_reparsing(self, counting):
        score = long_score()

        counting.render(score, page=1, width_px=1000, zoom=1)
        counting.render(score, page=1, width_px=600, zoom=1)
        # At 600 px, zoom 2 cannot fit the minimum layout width, so it lays out as zoom 1 did.
        counting.render(score, page=1, width_px=600, zoom=2)
        counting.render(score, page=1, width_px=600, zoom=0.5)

        [toolkit] = CountingToolkit.instances
        assert toolkit.loads == 1
        assert toolkit.relayouts == 2

    def test_a_different_score_is_loaded_afresh(self, counting):
        counting.render(VALID_MUSICXML, page=1, width_px=1000, zoom=1)
        result = counting.render(long_score(), page=2, width_px=1000, zoom=1)

        assert result["page"] == 2
        assert sum(t.loads for t in CountingToolkit.instances) == 2

    def test_a_failed_load_is_not_cached(self):
        renderer = SvgPageRenderer(RejectingToolkit)
        renderer.render(VALID_MUSICXML, page=1, width_px=1000, zoom=1)

        for _ in range(2):
            with pytest.raises(ProcessingError):
                renderer.render(UNREADABLE, page=1, width_px=1000, zoom=1)

        assert renderer.render(VALID_MUSICXML, page=1, width_px=1000, zoom=1)["page_count"] == 1


class TestTextFont:
    def test_keeps_verovio_embedding_its_text_font(self):
        """Tempo-mark note glyphs come from Verovio's SMuFL text font.

        No ``smuflTextFont`` mode renders them under the MCP Apps default CSP: ``embedded`` is a
        ``data:`` font (no font-src), ``linked`` imports from verovio.org and ``none`` needs the
        font installed. ``embedded`` is kept so hosts that allow ``data:`` fonts show them, and so
        the server pages match the WASM ones (docs/architecture.md, Score Viewer).
        """
        svg = SvgPageRenderer().render(VALID_MUSICXML.replace(
            "</attributes>",
            '</attributes><direction placement="above"><direction-type><metronome>'
            "<beat-unit>quarter</beat-unit><per-minute>90</per-minute></metronome></direction-type></direction>",
        ), page=1, width_px=1000, zoom=1)["svg"]

        assert "@font-face" in svg


def test_renders_from_a_worker_thread():
    # The server renders off the event loop. Verovio keeps its resource path per thread, set
    # only on the thread that imported it, so a toolkit made elsewhere finds no fonts.
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=1) as pool:
        page = pool.submit(SvgPageRenderer().render, VALID_MUSICXML, 1, 1000, 1).result()

    assert page["page_count"] >= 1
    assert "<svg" in page["svg"]
