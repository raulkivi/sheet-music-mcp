"""The error envelope every server returns (docs/conventions.md, Error Response Format).

No MCP imports: engines raise ``ProcessingError`` directly.
"""

from __future__ import annotations


def error_payload(
    message: str,
    error_code: str,
    *,
    hint: str | None = None,
    choices: list[str] | None = None,
) -> dict:
    """Return ``{"error", "error_code"}`` plus ``hint`` and ``choices`` when given."""
    payload: dict = {"error": message, "error_code": error_code}
    if hint is not None:
        payload["hint"] = hint
    if choices is not None:
        payload["choices"] = list(choices)
    return payload


class ProcessingError(Exception):
    """Raised when a processing step fails in an expected, reportable way."""

    def __init__(
        self,
        message: str,
        error_code: str = "PROCESSING_FAILED",
        *,
        hint: str | None = None,
        choices: list[str] | None = None,
    ):
        super().__init__(message)
        self.error_code = error_code
        self.hint = hint
        self.choices = choices

    def to_payload(self) -> dict:
        return error_payload(str(self), self.error_code, hint=self.hint, choices=self.choices)
