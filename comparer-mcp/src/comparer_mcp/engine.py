"""
Core comparison engine for comparer-mcp.

No MCP SDK imports here — this module is independently unit-testable, per
docs/architecture.md §2.

Orchestrates the layered comparison pipeline:
    part_matcher.match_parts()   -> matched/missing/extra parts
    (measure matching by number, inline below)
    note_aligner.align_notes()   -> per-measure note-level diff operations

Phase 1 scope (see docs/PLAN.md): part + measure + note-level comparison and
a weighted similarity score. Phase 2 adds key/time signature diffs,
voice-aware alignment, and articulation comparison.
"""

from pathlib import Path
from typing import Optional

from music21 import converter
from sheet_music_mcp_core.errors import ProcessingError  # re-exported for server.py
from sheet_music_mcp_core.measures import parse_range
from sheet_music_mcp_core.params import aliased
from sheet_music_mcp_core.parts import music21_part_infos, resolve_parts

from comparer_mcp.measure_comparator import (
    compare_key_signatures,
    compare_time_signatures,
    match_voices,
    measure_voices,
)
from comparer_mcp.models import (
    ComparisonResult,
    ComparisonSummary,
    MeasureDiff,
    NoteDiff,
    PartDiff,
)
from comparer_mcp.note_aligner import align_notes
from comparer_mcp.part_matcher import match_parts
from comparer_mcp.utils import note_to_info, validate_musicxml

# Note-diff operations that count as "partial matches" in the note-score term
# of the similarity formula (docs/architecture.md §5): right on one axis,
# wrong on the other.
_PARTIAL_MATCH_OPS = {"PITCH_CHANGE", "DURATION_CHANGE"}

_STRUCTURE_WEIGHT = 0.3
_NOTE_WEIGHT = 0.7


# Input formats (docs/requirements.md "Interfaces"): .musicxml, .xml, or
# compressed .mxl. compare_files() rejects anything else up front rather than
# letting an unrelated file type fall through to a generic parse failure
# (INVALID_INPUT) — see docs/HANDOVER.md "Known gotchas".
_SUPPORTED_FILE_EXTENSIONS = {".musicxml", ".xml", ".mxl"}


def _parse_score_from_string(xml_str: str):
    ok, reason = validate_musicxml(xml_str)
    if not ok:
        raise ProcessingError(reason, "INVALID_INPUT")
    try:
        return converter.parseData(xml_str, format="musicxml")
    except Exception as e:
        raise ProcessingError(f"Failed to parse MusicXML: {e}", "INVALID_INPUT")


def _parse_score_from_path(path: Path):
    # music21's path-based parser auto-detects and decompresses .mxl, unlike
    # the raw-string path above — so file input goes through this instead of
    # reading text and reusing _parse_score_from_string.
    try:
        return converter.parse(str(path))
    except Exception as e:
        raise ProcessingError(f"Failed to parse MusicXML file: {e}", "INVALID_INPUT")


def _measure_map(part) -> dict:
    """Map measure number -> Measure for a music21 Part."""
    return {m.number: m for m in part.getElementsByClass("Measure")}


def _interval_error(ref_info, tgt_info) -> Optional[int]:
    if ref_info is None or tgt_info is None:
        return None
    if ref_info.midi is None or tgt_info.midi is None:
        return None
    return abs(tgt_info.midi - ref_info.midi)


def _validate_part_filter(part_filter) -> None:
    if part_filter is None:
        return
    if not isinstance(part_filter, list) or not all(isinstance(n, str) for n in part_filter):
        raise ProcessingError(
            "options.parts must be a list of strings (part IDs, names or voices).",
            "INVALID_PARAMETER",
        )


def _select_parts(requested, reference_parts, reference_infos, target_parts, target_infos):
    """Resolve options.parts against the reference score (IDs, names or voices) and pick the
    target parts with the same names, or the same IDs when the selected parts are unnamed."""
    wanted = set(resolve_parts(requested, reference_infos))
    selected = [(p, i) for p, i in zip(reference_parts, reference_infos) if i.id in wanted]
    names = [i.name for _, i in selected]
    if all(names):
        targets = _filter_parts_by_name(target_parts, names)
    else:
        targets = [p for p, i in zip(target_parts, target_infos) if i.id in wanted]
    return [p for p, _ in selected], targets


def _part_label(info) -> str:
    return info.name or info.id


def _filter_parts_by_name(parts: list, part_filter: list) -> list:
    wanted = {name.strip().lower() for name in part_filter}
    return [p for p in parts if (p.partName or "").strip().lower() in wanted]


def _expand_repeats(score, label: str):
    try:
        expanded = score.expandRepeats()
    except Exception as e:
        raise ProcessingError(f"Failed to expand repeats in {label} score: {e}", "PROCESSING_FAILED")
    # expandRepeats() keeps each repeated measure's original number (e.g.
    # 1, 2, 1, 2), which would collide in _measure_map's number -> Measure
    # dict. Renumber sequentially so every unfolded measure survives.
    for part in expanded.parts:
        for i, measure in enumerate(part.getElementsByClass("Measure"), start=1):
            measure.number = i
    return expanded


def _apply_score_options(reference, target, options: Optional[dict]):
    """Apply options.expand_repeats / options.normalize_pitch (score-level
    transforms) and validate options.parts / options.measures (or their deprecated aliases
    options.part_filter / options.measure_range).

    options.measures filters the differences by measure number; unlike the other servers'
    ``measures``, it does not cut the scores (docs/research/ux-wave3-plan.md §3.4).

    expand_repeats and normalize_pitch return new music21 Score objects
    (music21 does not mutate in place), so the transformed reference/target
    must be returned and used for everything downstream — including
    annotation export, which needs to color notes on the same objects that
    were actually compared.
    """
    options = options or {}
    measures = parse_range(aliased(options, "measures", "measure_range"), param="options.measures")
    requested_parts = aliased(options, "parts", "part_filter")
    _validate_part_filter(requested_parts)

    if options.get("expand_repeats"):
        reference = _expand_repeats(reference, "reference")
        target = _expand_repeats(target, "target")

    if options.get("normalize_pitch"):
        reference = reference.toSoundingPitch()
        target = target.toSoundingPitch()

    return (
        reference,
        target,
        requested_parts,
        measures,
        bool(options.get("ignore_articulations")),
    )


def _compare_measure(
    measure_number: int,
    ref_measure,
    tgt_measure,
    ignore_articulations: bool = False,
    aligned_collector: Optional[list] = None,
) -> MeasureDiff:
    ref_voices = measure_voices(ref_measure)
    tgt_voices = measure_voices(tgt_measure)

    note_diffs = []
    for voice_number, ref_notes, tgt_notes in match_voices(ref_voices, tgt_voices):
        aligned = align_notes(ref_notes, tgt_notes)
        for op in aligned:
            ref_info = (
                note_to_info(op.reference, ignore_articulations) if op.reference is not None else None
            )
            tgt_info = (
                note_to_info(op.target, ignore_articulations) if op.target is not None else None
            )
            beat = float(op.reference.beat) if op.reference is not None else float(op.target.beat)
            note_diff = NoteDiff(
                measure_number=measure_number,
                beat=beat,
                voice=voice_number,
                operation=op.operation,
                reference=ref_info,
                target=tgt_info,
                interval_error=_interval_error(ref_info, tgt_info),
            )
            note_diffs.append(note_diff)
            if aligned_collector is not None:
                aligned_collector.append((note_diff, op))
    note_diffs.sort(key=lambda nd: (nd.voice, nd.beat))

    similarity = _note_score(note_diffs)

    ref_voice_count = len(ref_measure.voices) or 1
    tgt_voice_count = len(tgt_measure.voices) or 1

    return MeasureDiff(
        measure_number=measure_number,
        similarity_score=similarity,
        voice_count_reference=ref_voice_count,
        voice_count_target=tgt_voice_count,
        note_diffs=note_diffs,
    )


def _note_score(note_diffs: list) -> float:
    if not note_diffs:
        return 1.0
    identical = sum(1 for nd in note_diffs if nd.operation == "MATCH")
    partial = sum(1 for nd in note_diffs if nd.operation in _PARTIAL_MATCH_OPS)
    return (identical + 0.5 * partial) / len(note_diffs)


def _compare_part(
    ref_part,
    tgt_part,
    ref_info,
    tgt_info,
    measures: Optional[tuple[int, int]] = None,
    ignore_articulations: bool = False,
    aligned_collector: Optional[list] = None,
) -> PartDiff:
    ref_measures = _measure_map(ref_part)
    tgt_measures = _measure_map(tgt_part)

    all_numbers = sorted(set(ref_measures) | set(tgt_measures))
    if measures:
        start, end = measures
        all_numbers = [n for n in all_numbers if start <= n <= end]

    measure_diffs = []
    measures_missing = []
    measures_extra = []

    for number in all_numbers:
        ref_measure = ref_measures.get(number)
        tgt_measure = tgt_measures.get(number)
        if ref_measure is None:
            measures_extra.append(number)
        elif tgt_measure is None:
            measures_missing.append(number)
        else:
            measure_diffs.append(
                _compare_measure(
                    number, ref_measure, tgt_measure, ignore_articulations, aligned_collector
                )
            )

    all_note_diffs = [nd for md in measure_diffs for nd in md.note_diffs]
    note_score = _note_score(all_note_diffs)
    matched_measures = len(measure_diffs)
    if measures:
        start, end = measures
        ref_count = sum(1 for n in ref_measures if start <= n <= end)
        tgt_count = sum(1 for n in tgt_measures if start <= n <= end)
    else:
        ref_count, tgt_count = len(ref_measures), len(tgt_measures)
    total_measures = max(ref_count, tgt_count) or 1
    structure_score = matched_measures / total_measures
    similarity = _STRUCTURE_WEIGHT * structure_score + _NOTE_WEIGHT * note_score

    key_sig_diffs = compare_key_signatures(ref_part, tgt_part)
    time_sig_diffs = compare_time_signatures(ref_part, tgt_part)
    if measures:
        start, end = measures
        key_sig_diffs = [d for d in key_sig_diffs if start <= d.measure_number <= end]
        time_sig_diffs = [d for d in time_sig_diffs if start <= d.measure_number <= end]

    return PartDiff(
        part_name=ref_info.name or tgt_info.name or ref_info.id,
        reference_part_id=ref_info.id,
        target_part_id=tgt_info.id,
        similarity_score=similarity,
        key_sig_diffs=key_sig_diffs,
        time_sig_diffs=time_sig_diffs,
        measure_diffs=measure_diffs,
        measures_missing=measures_missing,
        measures_extra=measures_extra,
    )


def _build_summary(match_result, part_diffs: list, info_of: dict) -> ComparisonSummary:
    all_note_diffs = [nd for pd in part_diffs for md in pd.measure_diffs for nd in md.note_diffs]

    def _count(op):
        return sum(1 for nd in all_note_diffs if nd.operation == op)

    measures_missing = sum(len(pd.measures_missing) for pd in part_diffs)
    measures_extra = sum(len(pd.measures_extra) for pd in part_diffs)
    total_measures = sum(len(pd.measure_diffs) for pd in part_diffs) + measures_missing + measures_extra

    return ComparisonSummary(
        total_parts_reference=len(match_result.matched) + len(match_result.missing),
        total_parts_target=len(match_result.matched) + len(match_result.extra),
        parts_matched=len(match_result.matched),
        parts_missing=[_part_label(info_of[id(p)]) for p in match_result.missing],
        parts_extra=[_part_label(info_of[id(p)]) for p in match_result.extra],
        total_measures=total_measures,
        measures_missing=measures_missing,
        measures_extra=measures_extra,
        total_notes_compared=len(all_note_diffs),
        notes_identical=_count("MATCH"),
        notes_pitch_changed=_count("PITCH_CHANGE"),
        notes_duration_changed=_count("DURATION_CHANGE"),
        notes_substituted=_count("SUBSTITUTION"),
        notes_missing=_count("DELETION"),
        notes_extra=_count("INSERTION"),
        key_signature_diffs=sum(len(pd.key_sig_diffs) for pd in part_diffs),
        time_signature_diffs=sum(len(pd.time_sig_diffs) for pd in part_diffs),
    )


def _overall_similarity(match_result, part_diffs: list) -> float:
    total_parts = max(
        len(match_result.matched) + len(match_result.missing),
        len(match_result.matched) + len(match_result.extra),
    ) or 1
    part_structure_score = len(match_result.matched) / total_parts

    all_note_diffs = [nd for pd in part_diffs for md in pd.measure_diffs for nd in md.note_diffs]
    note_score = _note_score(all_note_diffs)

    total_measure_positions = sum(
        len(pd.measure_diffs) + len(pd.measures_missing) + len(pd.measures_extra) for pd in part_diffs
    )
    matched_measure_positions = sum(len(pd.measure_diffs) for pd in part_diffs)
    measure_structure_score = (
        matched_measure_positions / total_measure_positions if total_measure_positions else 1.0
    )

    structure_score = part_structure_score * measure_structure_score
    return _STRUCTURE_WEIGHT * structure_score + _NOTE_WEIGHT * note_score


def _compare_scores(reference, target, options: Optional[dict] = None, aligned_collector: Optional[list] = None):
    """Returns (ComparisonResult, reference, target) — reference/target are
    returned because options.expand_repeats/normalize_pitch produce new
    Score objects (music21 does not transform in place); callers that need
    to act on the same notes that were actually compared (e.g. annotation)
    must use these, not the objects originally passed in."""
    reference, target, part_filter, measures, ignore_articulations = _apply_score_options(
        reference, target, options
    )

    # Stable MusicXML part IDs, never music21's part.id (docs/conventions.md, Part Selection)
    reference_parts = list(reference.parts)
    target_parts = list(target.parts)
    reference_infos = music21_part_infos(reference_parts)
    target_infos = music21_part_infos(target_parts)
    info_of = {
        id(part): info
        for part, info in [*zip(reference_parts, reference_infos), *zip(target_parts, target_infos)]
    }
    if part_filter:
        reference_parts, target_parts = _select_parts(
            part_filter, reference_parts, reference_infos, target_parts, target_infos
        )

    match_result = match_parts(reference_parts, target_parts)
    part_diffs = [
        _compare_part(
            ref, tgt, info_of[id(ref)], info_of[id(tgt)], measures, ignore_articulations,
            aligned_collector,
        )
        for ref, tgt in match_result.matched
    ]

    result = ComparisonResult(
        similarity_score=_overall_similarity(match_result, part_diffs),
        summary=_build_summary(match_result, part_diffs, info_of),
        part_diffs=part_diffs,
    )
    return result, reference, target


def compare(reference_xml: str, target_xml: str, options: Optional[dict] = None) -> ComparisonResult:
    """Compare two MusicXML strings and return a full ComparisonResult."""
    reference = _parse_score_from_string(reference_xml)
    target = _parse_score_from_string(target_xml)
    result, _, _ = _compare_scores(reference, target, options)
    return result


def compare_files(reference: str, target: str, options: Optional[dict] = None) -> ComparisonResult:
    """Compare two MusicXML files (.musicxml, .xml, or compressed .mxl) and
    return a full ComparisonResult."""
    ref_path = Path(reference)
    tgt_path = Path(target)

    if not ref_path.exists():
        raise ProcessingError(f"Reference file not found: {reference}", "FILE_NOT_FOUND")
    if not tgt_path.exists():
        raise ProcessingError(f"Target file not found: {target}", "FILE_NOT_FOUND")

    if ref_path.suffix.lower() not in _SUPPORTED_FILE_EXTENSIONS:
        raise ProcessingError(
            f"Unsupported file extension for reference file: {ref_path.suffix or '(none)'}. "
            f"Supported: {', '.join(sorted(_SUPPORTED_FILE_EXTENSIONS))}.",
            "UNSUPPORTED_FORMAT",
        )
    if tgt_path.suffix.lower() not in _SUPPORTED_FILE_EXTENSIONS:
        raise ProcessingError(
            f"Unsupported file extension for target file: {tgt_path.suffix or '(none)'}. "
            f"Supported: {', '.join(sorted(_SUPPORTED_FILE_EXTENSIONS))}.",
            "UNSUPPORTED_FORMAT",
        )

    reference_score = _parse_score_from_path(ref_path)
    target_score = _parse_score_from_path(tgt_path)
    result, _, _ = _compare_scores(reference_score, target_score, options)
    return result


def compare_with_annotations(
    reference_xml: str, target_xml: str, options: Optional[dict] = None
):
    """Like compare(), but also returns the parsed (and, if options requested
    it, transformed) reference/target Score objects plus the raw
    (NoteDiff, AlignedNote) pairs produced during comparison — the building
    blocks comparer_mcp.annotator uses to color the actual note objects that
    were compared and re-serialize them to MusicXML.
    """
    reference = _parse_score_from_string(reference_xml)
    target = _parse_score_from_string(target_xml)
    aligned_collector: list = []
    result, reference, target = _compare_scores(
        reference, target, options, aligned_collector=aligned_collector
    )
    return result, reference, target, aligned_collector


_SMOKE_MUSICXML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Test</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
      </attributes>
      <note>
        <pitch><step>C</step><octave>4</octave></pitch>
        <duration>4</duration>
        <type>whole</type>
      </note>
    </measure>
  </part>
</score-partwise>
"""


def health_check() -> dict:
    """Run a smoke test to verify all runtime dependencies are working.

    Returns:
        {
            "status": "ok" | "degraded",
            "checks": {
                "music21": {"ok": bool, "version": str | None, "error": str | None},
                "self_compare": {"ok": bool, "error": str | None},
            },
            "summary": "human-readable status string",
        }
    """
    result: dict = {"status": "ok", "checks": {}, "summary": ""}

    try:
        import music21
        result["checks"]["music21"] = {"ok": True, "version": music21.__version__}
    except ImportError as e:
        result["checks"]["music21"] = {"ok": False, "version": None, "error": str(e)}
        result["status"] = "degraded"

    if result["status"] == "ok":
        try:
            comparison = compare(_SMOKE_MUSICXML, _SMOKE_MUSICXML)
            if comparison.similarity_score != 1.0:
                raise ValueError(
                    f"Self-comparison similarity was {comparison.similarity_score}, expected 1.0"
                )
            result["checks"]["self_compare"] = {"ok": True}
        except Exception as e:
            result["checks"]["self_compare"] = {"ok": False, "error": str(e)}
            result["status"] = "degraded"

    if result["status"] == "ok":
        version = result["checks"]["music21"]["version"]
        result["summary"] = f"All systems operational. music21 {version} is working correctly."
    else:
        issues = [
            f"{k}: {v.get('error', 'failed')}"
            for k, v in result["checks"].items()
            if not v.get("ok")
        ]
        result["summary"] = "Server is degraded: " + "; ".join(issues)

    return result
