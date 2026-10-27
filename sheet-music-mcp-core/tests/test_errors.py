"""The error envelope every server returns (docs/conventions.md, Error Response Format)."""

import pytest

from sheet_music_mcp_core.errors import ProcessingError, error_payload


class TestErrorPayload:
    def test_only_required_fields_when_no_extras(self):
        assert error_payload("Bad XML", "INVALID_INPUT") == {
            "error": "Bad XML",
            "error_code": "INVALID_INPUT",
        }

    def test_includes_hint_and_choices_when_given(self):
        payload = error_payload(
            "Part 'Sopran' not found",
            "INVALID_PARAMETER",
            hint="Pass one of the listed part names or IDs",
            choices=["Soprano (P1)", "Alto (P2)"],
        )

        assert payload == {
            "error": "Part 'Sopran' not found",
            "error_code": "INVALID_PARAMETER",
            "hint": "Pass one of the listed part names or IDs",
            "choices": ["Soprano (P1)", "Alto (P2)"],
        }

    def test_keeps_key_order_error_then_code(self):
        keys = list(error_payload("x", "Y", hint="h", choices=["c"]))

        assert keys == ["error", "error_code", "hint", "choices"]

    def test_empty_choices_are_kept(self):
        # An empty list still tells the model there is nothing valid to pick.
        assert error_payload("x", "Y", choices=[])["choices"] == []


class TestProcessingError:
    def test_defaults_to_processing_failed(self):
        error = ProcessingError("Rendering failed")

        assert str(error) == "Rendering failed"
        assert error.error_code == "PROCESSING_FAILED"
        assert error.hint is None
        assert error.choices is None

    def test_carries_code_hint_and_choices(self):
        error = ProcessingError("No parts", "INVALID_INPUT", hint="Check the file", choices=["a"])

        assert error.error_code == "INVALID_INPUT"
        assert error.hint == "Check the file"
        assert error.choices == ["a"]

    def test_to_payload_matches_error_payload(self):
        error = ProcessingError("No parts", "INVALID_INPUT", hint="Check the file")

        assert error.to_payload() == error_payload("No parts", "INVALID_INPUT", hint="Check the file")

    def test_is_an_exception(self):
        with pytest.raises(ProcessingError):
            raise ProcessingError("boom")
