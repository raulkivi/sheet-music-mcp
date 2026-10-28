"""The bounded TTL map behind artifact ids and server-side app state (proposal §6.4)."""

import threading

import pytest

from sheet_music_mcp_core.expiring import EntryNotFound, ExpiringTable

TTL = 60.0


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def clock():
    return FakeClock()


def _table(clock, **kwargs):
    kwargs.setdefault("ttl_seconds", TTL)
    kwargs.setdefault("max_entries", 8)
    return ExpiringTable(clock=clock, **kwargs)


class TestPutAndGet:
    def test_put_returns_an_unguessable_token(self, clock):
        table = _table(clock)

        first, second = table.put("a"), table.put("b")

        assert first != second
        assert len(first) >= 22  # at least 128 bits of token_urlsafe
        assert (table.get(first), table.get(second)) == ("a", "b")

    def test_set_stores_under_the_callers_key(self, clock):
        table = _table(clock)

        table.set(("session", 1), "state")

        assert table.get(("session", 1)) == "state"

    def test_set_replaces_an_existing_value(self, clock):
        table = _table(clock)
        table.set("k", 1)

        table.set("k", 2)

        assert table.get("k") == 2
        assert len(table) == 1

    def test_unknown_key_raises_entry_not_found(self, clock):
        with pytest.raises(EntryNotFound):
            _table(clock).get("nope")

    def test_entry_not_found_is_a_key_error(self):
        assert issubclass(EntryNotFound, KeyError)

    def test_entry_not_found_does_not_carry_the_key(self, clock):
        # Keys can come from a client; the caller decides what, if anything, to echo.
        with pytest.raises(EntryNotFound) as caught:
            _table(clock).get("../../etc/passwd")

        assert "passwd" not in str(caught.value)

    @pytest.mark.parametrize("key", [None, 42, ["a"], {"a": 1}])
    def test_odd_keys_are_just_unknown(self, clock, key):
        # JSON arguments can be anything; an unhashable one must not escape as TypeError.
        with pytest.raises(EntryNotFound):
            _table(clock).get(key)

    def test_len_counts_live_entries(self, clock):
        table = _table(clock)
        table.put("a")
        table.put("b")

        assert len(table) == 2


class TestExpiry:
    def test_entry_lives_until_the_ttl(self, clock):
        table = _table(clock)
        token = table.put("a")

        clock.advance(TTL - 0.001)

        assert table.get(token) == "a"

    def test_entry_expires_at_the_ttl(self, clock):
        table = _table(clock)
        token = table.put("a")

        clock.advance(TTL)

        with pytest.raises(EntryNotFound):
            table.get(token)
        assert len(table) == 0

    def test_reads_do_not_extend_the_ttl(self, clock):
        table = _table(clock)
        token = table.put("a")

        clock.advance(TTL / 2)
        table.get(token)
        clock.advance(TTL / 2)

        with pytest.raises(EntryNotFound):
            table.get(token)

    def test_set_again_restarts_the_ttl(self, clock):
        # A replaced value is a new insert, so its lifetime counts from the replacement.
        table = _table(clock)
        table.set("k", 1)
        clock.advance(TTL / 2)
        table.set("k", 2)
        clock.advance(TTL / 2)

        assert table.get("k") == 2

    def test_replaced_key_is_evicted_by_its_new_insert_time(self, clock):
        table = _table(clock, max_entries=2)
        table.set("old", 1)
        table.set("new", 2)
        table.set("old", 3)

        table.set("third", 4)

        assert table.get("old") == 3
        with pytest.raises(EntryNotFound):
            table.get("new")


class TestCapacity:
    def test_oldest_entry_goes_first(self, clock):
        table = _table(clock, max_entries=2)
        first = table.put("a")
        second = table.put("b")
        third = table.put("c")

        with pytest.raises(EntryNotFound):
            table.get(first)
        assert (table.get(second), table.get(third)) == ("b", "c")

    def test_expired_entries_free_room_before_eviction(self, clock):
        evicted = []
        table = _table(clock, max_entries=2, on_evict=lambda k, v: evicted.append(v))
        table.put("a")
        clock.advance(TTL)
        table.put("b")
        table.put("c")

        assert evicted == ["a"]
        assert len(table) == 2


class TestDiscard:
    def test_discard_removes_the_entry(self, clock):
        table = _table(clock)
        token = table.put("a")

        table.discard(token)

        with pytest.raises(EntryNotFound):
            table.get(token)

    def test_discard_of_an_unknown_key_is_a_no_op(self, clock):
        _table(clock).discard("nope")
        _table(clock).discard(["unhashable"])


class TestEvictionHook:
    def test_called_with_key_and_value_on_expiry(self, clock):
        evicted = []
        table = _table(clock, on_evict=lambda key, value: evicted.append((key, value)))
        token = table.put("a")

        clock.advance(TTL)
        len(table)

        assert evicted == [(token, "a")]

    def test_called_on_capacity_eviction(self, clock):
        evicted = []
        table = _table(clock, max_entries=1, on_evict=lambda key, value: evicted.append((key, value)))
        table.set("first", 1)

        table.set("second", 2)

        assert evicted == [("first", 1)]

    def test_not_called_for_discard_or_replacement(self, clock):
        # The caller made those changes, so it already knows; the hook reports only the table's own.
        evicted = []
        table = _table(clock, on_evict=lambda key, value: evicted.append(key))
        table.set("k", 1)
        table.set("k", 2)
        table.discard("k")

        assert evicted == []

    def test_hook_may_use_the_table(self, clock):
        # Called after the lock is released, so a side-table cleanup can call back in.
        table = None
        seen = []

        def on_evict(key, value):
            seen.append(len(table))

        table = _table(clock, max_entries=1, on_evict=on_evict)
        table.set("a", 1)
        table.set("b", 2)

        assert seen == [1]

    def test_hook_failure_is_logged_not_raised(self, clock, caplog):
        # The table has already changed; raising would lose put's token and skip later hooks.
        calls = []

        def on_evict(key, value):
            calls.append(key)
            raise RuntimeError("side table broke")

        table = _table(clock, max_entries=3, on_evict=on_evict)
        table.set("a", 1)
        table.set("b", 2)
        clock.advance(TTL)

        token = table.put(3)

        assert table.get(token) == 3
        assert calls == ["a", "b"]
        assert [str(r.exc_info[1]) for r in caplog.records] == ["side table broke"] * 2


class TestConfiguration:
    @pytest.mark.parametrize("ttl", [0, -1.0])
    def test_ttl_must_be_positive(self, clock, ttl):
        with pytest.raises(ValueError, match="ttl_seconds"):
            _table(clock, ttl_seconds=ttl)

    def test_max_entries_must_be_at_least_one(self, clock):
        with pytest.raises(ValueError, match="max_entries"):
            _table(clock, max_entries=0)

    def test_defaults_use_the_monotonic_clock(self):
        table = ExpiringTable(ttl_seconds=TTL, max_entries=4)
        token = table.put("a")

        assert table.get(token) == "a"


def test_concurrent_puts_keep_the_cap():
    table = ExpiringTable(ttl_seconds=TTL, max_entries=50)

    def worker():
        for _ in range(200):
            table.put(object())

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(table) == 50
