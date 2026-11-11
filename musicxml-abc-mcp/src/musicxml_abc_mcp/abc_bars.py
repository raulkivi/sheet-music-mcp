"""Split one ABC tune at its bar lines into one small tune per bar.

music21 re-bars ABC by the M: meter instead of following its bar lines (an overfull bar is split,
some short bars are merged), so ``apply_abc_edit`` cuts the bars itself and converts each one
alone. Every bar tune gets the key and unit note length in force where the bar starts, and a
meter long enough that music21 never splits it.

No MCP imports, no music21: plain text handling.
"""

from __future__ import annotations

import re

from sheet_music_mcp_core.errors import ProcessingError

__all__ = ["FREE_METER", "split_bars"]

# Longer than any real bar (16 whole notes), so music21 keeps each bar as one measure; much
# longer meters make music21 slow (1024/4 takes seconds per bar).
FREE_METER = "64/4"

_FIELD = re.compile(r"^([A-Za-z+]):(.*)$")
_INLINE_FIELD = re.compile(r"\[([A-Za-z]):([^\]]*)\]")
_VOLTA = re.compile(r"\[?[0-9][0-9,\-]*")
_BAR_CHARS = "|:]"
_HINT = "Pass one tune for one part: X:, M:, L: and K: header lines, then the bars separated by '|'."


def split_bars(abc: str) -> list[str]:
    """One standalone ABC tune per bar of ``abc``, in order.

    Header fields other than L: and K: are dropped (the score keeps its own title, meter and
    tempo); L: and K: changes in the body, as field lines or inline ``[K:...]``, apply to the
    bars after them. Comments and lyrics lines are dropped. Raises ProcessingError
    (INVALID_INPUT) for empty ABC, a missing K: line, several tunes or voices, or no bars.
    """
    if not abc or not abc.strip():
        raise ProcessingError("ABC string is empty.", "INVALID_INPUT", hint=_HINT)
    lines = [_strip_comment(line) for line in abc.splitlines()]
    header, body = _split_header(lines)
    scanner = _Scanner(header)
    for line in body:
        if not line.strip():
            continue
        if field := _FIELD.match(line.strip()):
            scanner.field(field.group(1), field.group(2).strip())
        else:
            scanner.music(line.rstrip().removesuffix("\\"))
    bars = scanner.finish()
    if not bars:
        raise ProcessingError("The ABC has no bars.", "INVALID_INPUT", hint=_HINT)
    return [_tune(state, text) for state, text in bars]


def _strip_comment(line: str) -> str:
    """The line without a ``%`` comment (a ``%`` inside a quoted annotation is kept)."""
    quoted = False
    for index, char in enumerate(line):
        if char == '"':
            quoted = not quoted
        elif char == "%" and not quoted:
            return line[:index]
    return line


def _split_header(lines: list[str]) -> tuple[dict[str, str], list[str]]:
    """The L: and K: in force after the header (which ends at the first K: line), and the body."""
    state: dict[str, str] = {}
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        field = _FIELD.match(stripped)
        if field is None:
            break
        if field.group(1) in ("L", "K"):
            state[field.group(1)] = field.group(2).strip()
        if field.group(1) == "K":
            return state, lines[index + 1 :]
    raise ProcessingError("The ABC has no K: (key) line.", "INVALID_INPUT", hint=f"{_HINT} K: ends the header.")


def _tune(state: dict[str, str], text: str) -> str:
    lines = ["X:1", f"M:{FREE_METER}"]
    if "L" in state:
        lines.append(f"L:{state['L']}")
    lines.append(f"K:{state['K']}")
    return "\n".join(lines) + "\n" + text


class _Scanner:
    """Collects bars from music lines; field changes apply from the next bar on."""

    def __init__(self, state: dict[str, str]):
        self.state = dict(state)
        self.bars: list[tuple[dict[str, str], str]] = []
        self.text = ""
        self.start_state: dict[str, str] | None = None

    def field(self, name: str, value: str) -> None:
        if name == "X":
            raise ProcessingError("The ABC holds several tunes; give the bars of one part.", "INVALID_INPUT", hint=_HINT)
        if name == "V":
            raise ProcessingError("The ABC holds voices (V:); give the bars of one part.", "INVALID_INPUT", hint=_HINT)
        if name in ("L", "K"):
            self.state[name] = value

    def music(self, line: str) -> None:
        index = 0
        while index < len(line):
            char = line[index]
            if char in "\"!+":
                end = line.find(char, index + 1)
                end = len(line) - 1 if end < 0 else end
                self._add(line[index : end + 1])
                index = end + 1
            elif char == "[":
                index = self._bracket(line, index)
            elif char in _BAR_CHARS:
                index = self._bar_line(line, index)
            else:
                self._add(char)
                index += 1
        self._add(" ")

    def finish(self) -> list[tuple[dict[str, str], str]]:
        self._close()
        return self.bars

    def _bracket(self, line: str, index: int) -> int:
        following = line[index + 1 : index + 2]
        if following == "|":
            return self._bar_line(line, index + 1)
        if following.isdigit():  # volta bracket [1, [2: a marker, not music
            return _VOLTA.match(line, index).end()
        end = line.find("]", index)
        end = len(line) - 1 if end < 0 else end
        self._add(line[index : end + 1])
        if inline := _INLINE_FIELD.fullmatch(line[index : end + 1]):
            self.field(inline.group(1), inline.group(2).strip())
        return end + 1

    def _bar_line(self, line: str, index: int) -> int:
        self._close()
        while index < len(line) and line[index] in _BAR_CHARS:
            index += 1
        if volta := _VOLTA.match(line, index):  # |1, :|2
            index = volta.end()
        return index

    def _add(self, text: str) -> None:
        if not self.text.strip() and text.strip():
            self.start_state = dict(self.state)
        self.text += text

    def _close(self) -> None:
        if self.text.strip():
            self.bars.append((self.start_state, " ".join(self.text.split())))
        self.text = ""
        self.start_state = None
