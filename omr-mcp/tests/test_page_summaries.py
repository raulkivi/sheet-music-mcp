"""recognize_images reports what each page contributed, for the Recognition Review's page strip."""

import omr_mcp.omr_engine as engine


def _page(staves, measures):
    return {"musicxml": "<x/>", "metadata": {"staves_detected": staves, "measures": measures,
                                             "processing_time_ms": 1, "engine": "oemer"}}


def test_multi_page_result_lists_every_page(monkeypatch):
    pages = iter([_page(2, 8), _page(1, 5)])
    monkeypatch.setattr(engine, "recognize_image", lambda path, engine="oemer": next(pages))
    monkeypatch.setattr(engine, "_merge_musicxml_pages", lambda xmls: "<merged/>")
    monkeypatch.setattr(engine, "_audiveris_precheck", lambda path, name: None)

    result = engine.recognize_images(["a.png", "b.png"])

    assert result["_pages"] == [
        {"index": 1, "staves_detected": 2, "measures": 8},
        {"index": 2, "staves_detected": 1, "measures": 5},
    ]


def test_single_page_result_lists_that_page(monkeypatch):
    monkeypatch.setattr(engine, "recognize_image", lambda path, engine="oemer": _page(4, 8))
    monkeypatch.setattr(engine, "_audiveris_precheck", lambda path, name: None)

    result = engine.recognize_images(["a.png"])

    assert result["_pages"] == [{"index": 1, "staves_detected": 4, "measures": 8}]
