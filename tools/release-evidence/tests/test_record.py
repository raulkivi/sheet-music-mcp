"""The schema-1 record: serialising, parsing and the stable test ids."""

import json

import pytest

from release_evidence.record import (
    RecordError,
    CheckResult,
    from_dict,
    id_of,
    titled,
    to_dict,
)

from .helpers import SHA, evidence, record_dict


class TestTitles:
    def test_title_starts_with_the_id(self):
        assert titled("PM1", "load start poll stop") == "PM1 load start poll stop"

    @pytest.mark.parametrize("title, id_", [
        ("PM1 load", "PM1"), ("M0 Engine line", "M0"), ("PM12 x", "PM12"),
    ])
    def test_id_of(self, title, id_):
        assert id_of(title) == id_

    @pytest.mark.parametrize("title", ["load PM1", "pm1 load", "PM1", "PM1_load", "1 load", ""])
    def test_no_id(self, title):
        assert id_of(title) is None


class TestToDict:
    def test_fields_in_schema_order(self):
        data = to_dict(evidence())
        assert list(data) == [
            "schema", "suite", "commit", "dirty", "versions", "environment", "tests", "ranAt", "notes",
        ]
        assert data["schema"] == 1
        assert data["environment"] == {"platform": "linux", "inputDevice": "usb"}
        assert data["tests"][0] == {"title": "PM1 load start poll stop", "state": "passed", "skipReason": None}

    def test_round_trip(self):
        original = evidence(tests=(CheckResult("PM1 x", "skipped", "no mic"),), notes="ok")
        assert from_dict(json.loads(json.dumps(to_dict(original)))) == original


def _error(data) -> RecordError:
    with pytest.raises(RecordError) as exc:
        from_dict(data)
    return exc.value


class TestFromDict:
    def test_valid(self):
        parsed = from_dict(record_dict())
        assert parsed.commit == SHA
        assert parsed.tests == (CheckResult("PM1 load", "passed"),)
        assert parsed.environment.input_device == "usb"

    def test_null_input_device_is_allowed(self):
        data = record_dict(environment={"platform": "macos", "inputDevice": None})
        assert from_dict(data).environment.input_device is None

    def test_sha256_commit_is_allowed(self):
        assert from_dict(record_dict(commit="c" * 64)).commit == "c" * 64

    @pytest.mark.parametrize("value", [2, 0])
    def test_unknown_schema(self, value):
        error = _error(record_dict(schema=value))
        assert error.code == "unknown-schema"
        assert str(value) in error.message

    @pytest.mark.parametrize("value", [None, "1", 1.0, True])
    def test_no_schema_version_is_malformed(self, value):
        assert _error(record_dict(schema=value)).code == "malformed"

    def test_not_an_object(self):
        assert _error([1]).code == "malformed"

    @pytest.mark.parametrize("field, value, words", [
        ("suite", "nope", "suite"),
        ("commit", "abc", "commit"),
        ("commit", "A" * 40, "commit"),
        ("dirty", "no", "dirty"),
        ("versions", {"pitch-mcp": ""}, "versions"),
        ("versions", ["0.4.0"], "versions"),
        ("versions", {"x": "1\n2"}, "versions"),
        ("environment", {"platform": "my-laptop", "inputDevice": "usb"}, "platform"),
        ("environment", {"platform": "linux", "inputDevice": "Raul's AirPods"}, "inputDevice"),
        ("environment", {"platform": "linux"}, "environment"),
        ("tests", [{"title": "PM1", "state": "ok", "skipReason": None}], "tests"),
        ("tests", [{"title": "", "state": "passed", "skipReason": None}], "tests"),
        ("tests", [{"title": "PM1", "state": "passed"}], "tests"),
        ("tests", "PM1", "tests"),
        ("ranAt", "yesterday", "ranAt"),
        ("ranAt", "2026-13-45T00:00:00Z", "ranAt"),
        ("notes", None, "notes"),
    ])
    def test_malformed_field_is_named(self, field, value, words):
        error = _error(record_dict(**{field: value}))
        assert error.code == "malformed"
        assert words in error.message

    def test_missing_field_is_named(self):
        data = record_dict()
        del data["ranAt"]
        error = _error(data)
        assert error.code == "malformed"
        assert "ranAt" in error.message

    def test_unknown_field_is_named(self):
        error = _error(record_dict(hostname="box"))
        assert error.code == "malformed"
        assert "hostname" in error.message
