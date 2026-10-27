"""Score references: scores passed and returned as file paths (docs/conventions.md, Score References).

The five comparison tools take ``reference_xml`` or ``reference_path`` and ``target_xml`` or
``target_path`` (exactly one of each pair). ``compare_musicxml_files`` reads through the shared
read policy. ``export_annotated_musicxml`` returns paths for large results (``return``), and the
shared ``describe_score`` tool is exposed. The real engine runs: it is fast on these small scores.
"""

import json
import shutil
import zipfile
from pathlib import Path

import pytest
from mcp import Client
from music21 import corpus
from sheet_music_mcp_core.references import SCORE_MIME_TYPE, exactly_one

from comparer_mcp.annotator import annotate
from comparer_mcp.engine import compare_files
from comparer_mcp.server import app, call_tool, list_tools

from .test_part_selection import SATB_REF
from .test_server import REFERENCE_XML, TARGET_XML, _score_xml

SENTINEL = "SENTINEL-outside-file-must-not-leak"

PAIR_TOOLS = (
    "compare_musicxml",
    "quick_similarity",
    "list_changes",
    "generate_comparison_report",
    "export_annotated_musicxml",
)
PAIR_NAMES = {"reference_xml", "reference_path", "target_xml", "target_path"}
ANNOTATED_FIELDS = ("reference_annotated_musicxml", "target_annotated_musicxml")

CONTAINER_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<container>
  <rootfiles>
    <rootfile full-path="score.musicxml" media-type="application/vnd.recordare.musicxml+xml"/>
  </rootfiles>
</container>"""

# Two 16-measure parts: the annotated pair is well above the 8 KB inline limit.
BIG_REFERENCE_XML = _score_xml({"Soprano": [("C4", 1.0)] * 64, "Alto": [("E4", 1.0)] * 64})
BIG_TARGET_XML = _score_xml(
    {"Soprano": [("C4", 1.0)] * 63 + [("D4", 1.0)], "Alto": [("E4", 1.0)] * 64}
)


@pytest.fixture
def root(tmp_path, monkeypatch):
    """The output root (and so a read root), separate from files placed outside it."""
    path = tmp_path / "root"
    path.mkdir()
    monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(path))
    monkeypatch.delenv("SHEET_MUSIC_INPUT_ROOTS", raising=False)
    monkeypatch.delenv("SHEET_MUSIC_INLINE_MAX_BYTES", raising=False)
    return path


@pytest.fixture
def files(root):
    """Reference and target as .musicxml files in the root."""
    reference = root / "reference.musicxml"
    target = root / "target.musicxml"
    reference.write_text(REFERENCE_XML, encoding="utf-8")
    target.write_text(TARGET_XML, encoding="utf-8")
    return reference, target


def _write_mxl(path: Path, text: str, *, container: bool = True) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        if container:
            archive.writestr("META-INF/container.xml", CONTAINER_XML)
            archive.writestr("score.musicxml", text)
        else:
            archive.writestr("plain.xml", text)
    return path


@pytest.fixture
def outside_file(tmp_path):
    folder = tmp_path / "outside"
    folder.mkdir()
    path = folder / "secret.musicxml"
    path.write_text(
        REFERENCE_XML.replace("<score-partwise", f"<!-- {SENTINEL} --><score-partwise", 1),
        encoding="utf-8",
    )
    return path


def _error(result):
    assert len(result) == 1
    return json.loads(result[0].text)


async def _schema(tool):
    return next(t for t in await list_tools() if t.name == tool).input_schema


async def _call_client(tool, arguments):
    async with Client(app) as client:
        return await client.call_tool(tool, arguments)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class TestSchemas:
    @pytest.mark.parametrize("tool", PAIR_TOOLS)
    async def test_pair_tools_take_inline_or_path_for_each_side(self, tool):
        schema = await _schema(tool)

        assert PAIR_NAMES <= set(schema["properties"])
        assert schema["allOf"] == [
            exactly_one("reference_xml", "reference_path"),
            exactly_one("target_xml", "target_path"),
        ]
        assert not PAIR_NAMES & set(schema.get("required", []))

    @pytest.mark.parametrize("tool", PAIR_TOOLS)
    async def test_inline_descriptions_keep_their_text_and_name_the_path(self, tool):
        properties = (await _schema(tool))["properties"]

        assert properties["reference_xml"]["description"].startswith("Reference MusicXML document")
        assert "'reference_path'" in properties["reference_xml"]["description"]
        assert "'target_path'" in properties["target_xml"]["description"]
        assert ".mxl" in properties["reference_path"]["description"]

    async def test_compare_musicxml_files_keeps_both_paths_required(self):
        schema = await _schema("compare_musicxml_files")

        assert set(schema["required"]) == {"reference_path", "target_path"}
        assert "allOf" not in schema

    async def test_export_takes_return_mode(self):
        schema = await _schema("export_annotated_musicxml")

        assert schema["properties"]["return"]["enum"] == ["auto", "path", "inline"]
        assert schema["properties"]["return"]["default"] == "auto"

    async def test_export_description_points_to_render_paths(self):
        tool = next(t for t in await list_tools() if t.name == "export_annotated_musicxml")

        assert "musicxml_path" in tool.description
        assert "both take a raw musicxml string" not in tool.description

    async def test_describe_score_is_listed(self):
        assert "describe_score" in {t.name for t in await list_tools()}

    async def test_capabilities_list_describe_score_and_mxl(self):
        data = json.loads((await call_tool("list_capabilities", {}))[0].text)

        assert "describe_score" in data["tools"]
        assert "mxl" in data["input_formats"]
        assert data["input_parameters"] == ["reference_xml", "reference_path", "target_xml", "target_path"]


# ---------------------------------------------------------------------------
# A path call gives the same result as the inline call
# ---------------------------------------------------------------------------


class TestPathEqualsInline:
    @pytest.mark.parametrize("tool", PAIR_TOOLS)
    async def test_both_paths(self, tool, files):
        reference, target = files
        inline = await call_tool(tool, {"reference_xml": REFERENCE_XML, "target_xml": TARGET_XML})
        by_path = await call_tool(tool, {"reference_path": str(reference), "target_path": str(target)})

        assert "error" not in json.loads(inline[0].text)
        assert by_path[0].text == inline[0].text

    @pytest.mark.parametrize("tool", PAIR_TOOLS)
    async def test_one_path_one_inline(self, tool, files):
        reference, _ = files
        inline = await call_tool(tool, {"reference_xml": REFERENCE_XML, "target_xml": TARGET_XML})
        mixed = await call_tool(tool, {"reference_path": str(reference), "target_xml": TARGET_XML})

        assert mixed[0].text == inline[0].text

    async def test_relative_paths_resolve_against_output_root(self, files):
        inline = await call_tool(
            "quick_similarity", {"reference_xml": REFERENCE_XML, "target_xml": TARGET_XML}
        )
        relative = await call_tool(
            "quick_similarity", {"reference_path": "reference.musicxml", "target_path": "target.musicxml"}
        )

        assert relative[0].text == inline[0].text

    @pytest.mark.parametrize("container", [True, False], ids=["container", "no-container"])
    async def test_mxl_paths(self, root, container):
        reference = _write_mxl(root / "reference.mxl", REFERENCE_XML, container=container)
        target = _write_mxl(root / "target.mxl", TARGET_XML, container=container)
        inline = await call_tool("compare_musicxml", {"reference_xml": REFERENCE_XML, "target_xml": TARGET_XML})

        by_path = await call_tool(
            "compare_musicxml", {"reference_path": str(reference), "target_path": str(target)}
        )

        assert by_path[0].text == inline[0].text

    async def test_list_changes_filters_still_apply(self, files):
        reference, target = files
        arguments = {"part": "Soprano", "measure_range": [1, 1]}
        inline = await call_tool(
            "list_changes", {"reference_xml": REFERENCE_XML, "target_xml": TARGET_XML, **arguments}
        )
        by_path = await call_tool(
            "list_changes", {"reference_path": str(reference), "target_path": str(target), **arguments}
        )

        assert json.loads(by_path[0].text)["count"] == 1
        assert by_path[0].text == inline[0].text


# ---------------------------------------------------------------------------
# compare_musicxml_files: shared read policy, same result as the engine's compare_files
# ---------------------------------------------------------------------------


class TestCompareMusicxmlFiles:
    async def test_same_content_as_compare_musicxml(self, files):
        reference, target = files
        inline = await call_tool("compare_musicxml", {"reference_xml": REFERENCE_XML, "target_xml": TARGET_XML})

        by_files = await call_tool(
            "compare_musicxml_files", {"reference_path": str(reference), "target_path": str(target)}
        )

        assert by_files[0].text == inline[0].text

    @pytest.mark.parametrize("options", [None, {"expand_repeats": True}, {"parts": ["P1"]}])
    async def test_real_mxl_matches_engine_compare_files(self, root, options):
        # A real compressed chorale from music21's corpus, against a plain .musicxml export.
        mxl = Path(str(corpus.getWork("bach/bwv66.6")))
        assert mxl.suffix == ".mxl"
        reference = root / "chorale.mxl"
        shutil.copyfile(mxl, reference)
        target = root / "target.musicxml"
        target.write_text(TARGET_XML, encoding="utf-8")
        arguments = {"reference_path": str(reference), "target_path": str(reference)}
        if options:
            arguments["options"] = options

        same = await call_tool("compare_musicxml_files", arguments)
        different = await call_tool(
            "compare_musicxml_files", {**arguments, "target_path": str(target)}
        )

        expected_same = compare_files(str(reference), str(reference), options).to_dict()
        expected_different = compare_files(str(reference), str(target), options).to_dict()
        assert json.loads(same[0].text) == expected_same
        assert json.loads(different[0].text) == expected_different
        assert expected_same["similarity_score"] == 1.0

    async def test_path_outside_roots_is_rejected_without_content(self, root, files, outside_file):
        reference, _ = files
        data = _error(
            await call_tool(
                "compare_musicxml_files",
                {"reference_path": str(reference), "target_path": str(outside_file)},
            )
        )

        assert data["error_code"] == "INVALID_PARAMETER"
        assert "target_path" in data["error"]
        assert "SHEET_MUSIC_INPUT_ROOTS" in data["hint"]
        assert SENTINEL not in json.dumps(data)

    async def test_input_roots_allow_an_outside_folder(self, files, outside_file, monkeypatch):
        reference, _ = files
        monkeypatch.setenv("SHEET_MUSIC_INPUT_ROOTS", str(outside_file.parent))

        result = await call_tool(
            "compare_musicxml_files",
            {"reference_path": str(reference), "target_path": str(outside_file)},
        )

        assert "similarity_score" in json.loads(result[0].text)

    async def test_wrong_suffix_is_invalid_parameter(self, files, root):
        reference, _ = files
        other = root / "target.pdf"
        other.write_text("not a score")

        data = _error(
            await call_tool(
                "compare_musicxml_files", {"reference_path": str(reference), "target_path": str(other)}
            )
        )

        assert data["error_code"] == "INVALID_PARAMETER"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class TestPathErrors:
    @pytest.mark.parametrize("tool", PAIR_TOOLS)
    async def test_absolute_path_outside_roots(self, tool, root, outside_file):
        data = _error(await call_tool(tool, {"reference_path": str(outside_file), "target_xml": TARGET_XML}))

        assert data["error_code"] == "INVALID_PARAMETER"
        assert "reference_path" in data["error"]
        assert SENTINEL not in json.dumps(data)

    @pytest.mark.parametrize("path", ["/etc/passwd", "../x.musicxml", "../outside/secret.musicxml"])
    async def test_paths_escaping_the_roots(self, root, outside_file, path):
        data = _error(await call_tool("compare_musicxml", {"reference_xml": REFERENCE_XML, "target_path": path}))

        assert data["error_code"] == "INVALID_PARAMETER"
        assert "target_path" in data["error"]
        assert SENTINEL not in json.dumps(data)

    async def test_symlink_in_root_pointing_outside(self, root, outside_file):
        link = root / "link.musicxml"
        link.symlink_to(outside_file)

        data = _error(await call_tool("quick_similarity", {"reference_path": str(link), "target_xml": TARGET_XML}))

        assert data["error_code"] == "INVALID_PARAMETER"
        assert SENTINEL not in json.dumps(data)

    async def test_missing_file(self, root):
        data = _error(
            await call_tool(
                "compare_musicxml", {"reference_path": str(root / "missing.musicxml"), "target_xml": TARGET_XML}
            )
        )

        assert data["error_code"] == "FILE_NOT_FOUND"

    async def test_file_that_is_not_musicxml(self, root):
        path = root / "notes.xml"
        path.write_text("<html><body>not a score</body></html>")

        data = _error(await call_tool("compare_musicxml", {"reference_path": str(path), "target_xml": TARGET_XML}))

        assert data["error_code"] == "INVALID_INPUT"
        assert data["error"].startswith("reference_path:")
        assert "not a score" not in data["error"]

    async def test_inline_errors_keep_their_prefix(self, files):
        _, target = files
        data = _error(await call_tool("compare_musicxml", {"reference_xml": "not xml", "target_path": str(target)}))

        assert data["error_code"] == "INVALID_INPUT"
        assert data["error"].startswith("reference_xml: ")

    @pytest.mark.parametrize("tool", PAIR_TOOLS)
    async def test_both_of_a_pair_through_the_protocol(self, tool, files):
        reference, _ = files
        result = await _call_client(
            tool, {"reference_xml": REFERENCE_XML, "reference_path": str(reference), "target_xml": TARGET_XML}
        )

        assert result.is_error
        data = json.loads(result.content[0].text)
        assert data["error_code"] == "INVALID_PARAMETER"
        assert "only one" in data["error"]
        assert "reference_path" in data["error"]
        assert "<score-partwise" not in data["error"]

    @pytest.mark.parametrize("tool", PAIR_TOOLS)
    async def test_neither_of_a_pair_through_the_protocol(self, tool):
        result = await _call_client(tool, {"reference_xml": REFERENCE_XML})

        assert result.is_error
        data = json.loads(result.content[0].text)
        assert data["error_code"] == "INVALID_PARAMETER"
        assert "target_path" in data["error"]
        assert "<score-partwise" not in data["error"]

    async def test_both_of_a_pair_in_a_direct_call(self, files):
        reference, _ = files
        data = _error(
            await call_tool(
                "compare_musicxml",
                {"reference_xml": REFERENCE_XML, "reference_path": str(reference), "target_xml": TARGET_XML},
            )
        )

        assert data["error_code"] == "INVALID_PARAMETER"


# ---------------------------------------------------------------------------
# export_annotated_musicxml returns paths for large results (C25)
# ---------------------------------------------------------------------------


class TestExportAnnotatedReturn:
    async def test_small_inputs_stay_inline_and_unchanged(self, root):
        result = await call_tool(
            "export_annotated_musicxml", {"reference_xml": REFERENCE_XML, "target_xml": TARGET_XML}
        )

        assert len(result) == 1
        assert result[0].text == json.dumps(annotate(REFERENCE_XML, TARGET_XML), indent=2)
        assert not (root / "scores").exists()

    async def test_auto_writes_both_files_above_the_limit(self, root):
        result = await call_tool(
            "export_annotated_musicxml", {"reference_xml": BIG_REFERENCE_XML, "target_xml": BIG_TARGET_XML}
        )
        data = json.loads(result[0].text)

        assert "<score-partwise" not in result[0].text
        for field in ANNOTATED_FIELDS:
            assert field not in data
            path = Path(data[f"{field}_path"])
            assert path.parent == root / "scores"
            assert path.name.startswith(f"annotated-{field}-")
            assert "<score-partwise" in path.read_text(encoding="utf-8")
            assert [part["name"] for part in data["score_summary"][field]["parts"]] == ["Soprano", "Alto"]
            assert data["score_summary"][field]["measures"] == 16
        assert set(data["score_summary"]) == set(ANNOTATED_FIELDS)
        assert data["similarity_score"] < 1.0
        assert "legend" in data

        links = result[1:]
        assert [block.type for block in links] == ["resource_link", "resource_link"]
        assert {block.mime_type for block in links} == {SCORE_MIME_TYPE}
        assert {block.uri for block in links} == {
            Path(data[f"{field}_path"]).as_uri() for field in ANNOTATED_FIELDS
        }

    async def test_written_files_hold_the_annotated_scores(self, root):
        arguments = {"reference_xml": BIG_REFERENCE_XML, "target_xml": BIG_TARGET_XML}
        inline = json.loads((await call_tool("export_annotated_musicxml", {**arguments, "return": "inline"}))[0].text)
        by_path = json.loads((await call_tool("export_annotated_musicxml", arguments))[0].text)

        for field in ANNOTATED_FIELDS:
            assert Path(by_path[f"{field}_path"]).read_text(encoding="utf-8") == inline[field]
        assert 'color="#FF8800"' in inline["target_annotated_musicxml"]

    async def test_inline_mode_keeps_large_text(self, root):
        result = await call_tool(
            "export_annotated_musicxml",
            {"reference_xml": BIG_REFERENCE_XML, "target_xml": BIG_TARGET_XML, "return": "inline"},
        )

        assert len(result) == 1
        assert "<score-partwise" in json.loads(result[0].text)["reference_annotated_musicxml"]
        assert not (root / "scores").exists()

    async def test_path_mode_writes_small_results(self, root):
        result = await call_tool(
            "export_annotated_musicxml",
            {"reference_xml": REFERENCE_XML, "target_xml": TARGET_XML, "return": "path"},
        )
        data = json.loads(result[0].text)

        assert {f"{field}_path" for field in ANNOTATED_FIELDS} <= set(data)
        assert len(result) == 3

    async def test_returned_paths_feed_back_in(self, root):
        first = json.loads(
            (
                await call_tool(
                    "export_annotated_musicxml",
                    {"reference_xml": BIG_REFERENCE_XML, "target_xml": BIG_TARGET_XML},
                )
            )[0].text
        )

        result = await call_tool(
            "quick_similarity",
            {
                "reference_path": first["reference_annotated_musicxml_path"],
                "target_path": first["target_annotated_musicxml_path"],
            },
        )

        assert json.loads(result[0].text)["similarity_score"] == first["similarity_score"]

    async def test_errors_are_not_wrapped(self, root):
        data = _error(
            await call_tool("export_annotated_musicxml", {"reference_xml": "not xml", "target_xml": TARGET_XML})
        )

        assert data["error_code"] == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# describe_score
# ---------------------------------------------------------------------------


class TestDescribeScore:
    async def test_inline(self):
        data = json.loads((await call_tool("describe_score", {"musicxml": SATB_REF}))[0].text)

        assert [part["id"] for part in data["parts"]] == ["P1", "P2", "P3", "P4"]
        assert [part["name"] for part in data["parts"]] == ["Soprano", "Alto", "Tenor", "Bass"]
        assert data["time"] == "4/4"

    async def test_path(self, root):
        path = root / "satb.musicxml"
        path.write_text(SATB_REF, encoding="utf-8")

        data = json.loads((await call_tool("describe_score", {"musicxml_path": str(path)}))[0].text)

        assert [part["id"] for part in data["parts"]] == ["P1", "P2", "P3", "P4"]

    async def test_path_outside_roots(self, root, outside_file):
        data = _error(await call_tool("describe_score", {"musicxml_path": str(outside_file)}))

        assert data["error_code"] == "INVALID_PARAMETER"
        assert SENTINEL not in json.dumps(data)

    async def test_through_the_protocol(self, files):
        reference, _ = files
        result = await _call_client("describe_score", {"musicxml_path": str(reference)})

        assert not result.is_error
        assert json.loads(result.content[0].text)["measures"] == 1
