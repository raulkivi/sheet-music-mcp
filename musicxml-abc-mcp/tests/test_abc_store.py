"""AbcStore: opaque, bounded, expiring handles to musicxml_to_abc results (proposal 5.6, AC-A2)."""

import pytest
from sheet_music_mcp_core.errors import ProcessingError

from musicxml_abc_mcp.abc_store import AbcStore

RESULT = {"abc": "X:1\nK:C\nC|]", "parts_included": ["P1"], "warnings": ["w"]}


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_put_returns_a_new_id_each_time_even_for_identical_input():
    store = AbcStore()

    ids = {store.put(RESULT) for _ in range(20)}

    assert len(ids) == 20


def test_get_returns_what_was_put():
    store = AbcStore()
    abc_id = store.put(RESULT)

    assert store.get(abc_id) == RESULT


def test_get_without_an_id_is_the_latest():
    store = AbcStore()
    store.put(RESULT)
    store.put({**RESULT, "abc": "second"})

    assert store.get(None)["abc"] == "second"


def test_nothing_stored_is_an_error_with_a_hint():
    with pytest.raises(ProcessingError) as caught:
        AbcStore().get(None)

    assert caught.value.error_code == "INVALID_PARAMETER"
    assert "musicxml_to_abc" in caught.value.to_payload()["hint"]


@pytest.mark.parametrize("bad", ["nope", "../../etc/passwd", "/etc/passwd", 7])
def test_unknown_ids_are_rejected_without_being_echoed(bad):
    store = AbcStore()
    store.put(RESULT)

    with pytest.raises(ProcessingError) as caught:
        store.get(bad)

    assert caught.value.error_code == "INVALID_PARAMETER"
    assert str(bad) not in str(caught.value)


def test_entries_expire_after_the_ttl():
    clock = Clock()
    store = AbcStore(ttl_seconds=10, clock=clock)
    abc_id = store.put(RESULT)
    clock.now = 11

    with pytest.raises(ProcessingError):
        store.get(abc_id)


def test_the_oldest_entries_go_first_when_full():
    store = AbcStore(max_entries=2)
    first = store.put(RESULT)
    second = store.put(RESULT)
    third = store.put(RESULT)

    with pytest.raises(ProcessingError):
        store.get(first)
    assert store.get(second) and store.get(third)


def test_returned_data_cannot_change_the_stored_copy():
    store = AbcStore()
    abc_id = store.put(RESULT)

    store.get(abc_id)["warnings"].append("tampered")

    assert store.get(abc_id)["warnings"] == ["w"]
