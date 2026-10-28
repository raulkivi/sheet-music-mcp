"""Opaque artifact handles for MCP Apps (mcp-apps-ux-proposal.md §5.2, §6.3 rule 3, §7)."""

import base64
import os
from pathlib import Path

import pytest

from sheet_music_mcp_core.artifacts import (
    MAX_CHUNK_BYTES,
    ArtifactError,
    ArtifactInfo,
    ArtifactStore,
    FileArtifactStore,
    InMemoryArtifactStore,
    chunk_payload,
)
from sheet_music_mcp_core.errors import ProcessingError

PAYLOAD = bytes(range(256)) * 41  # 10,496 bytes, every byte value, not a chunk multiple


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


@pytest.fixture
def root(tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(out))
    return out.resolve()


def _write(folder: Path, name="track.wav", data=PAYLOAD) -> Path:
    path = folder / name
    path.write_bytes(data)
    return path


def _file_store(root, clock, **kwargs):
    return FileArtifactStore(root, clock=clock, **kwargs)


def _memory_store(root, clock, **kwargs):
    return InMemoryArtifactStore(clock=clock, **kwargs)


@pytest.fixture(params=[_file_store, _memory_store], ids=["file", "memory"])
def make_store(request, root, clock):
    """Both stores honour the same contract, so either can be injected (proposal §6.4, L)."""
    return lambda **kwargs: request.param(root, clock, **kwargs)


def _error(excinfo) -> dict:
    return excinfo.value.to_payload()


class TestContract:
    def test_both_stores_satisfy_the_protocol(self, make_store):
        assert isinstance(make_store(), ArtifactStore)

    def test_put_returns_an_opaque_unguessable_id(self, make_store, root):
        store = make_store()
        path = _write(root)

        first = store.put(path, "audio/wav")
        second = store.put(path, "audio/wav")

        assert first != second
        assert len(first) >= 22  # at least 128 bits of token_urlsafe
        assert "track" not in first and "/" not in first and "wav" not in first

    def test_info_reports_kind_and_length_without_a_path(self, make_store, root):
        store = make_store()
        artifact_id = store.put(_write(root), "audio/wav")

        info = store.info(artifact_id)

        assert info == ArtifactInfo(artifact_id=artifact_id, kind="audio/wav", byte_length=len(PAYLOAD))
        assert str(root) not in repr(info)

    def test_chunks_over_the_whole_length_equal_the_file_bytes(self, make_store, root):
        """AC-S3."""
        store = make_store()
        artifact_id = store.put(_write(root), "audio/wav")
        length = store.info(artifact_id).byte_length

        chunks = [store.read_chunk(artifact_id, offset, 1000) for offset in range(0, length, 1000)]

        assert b"".join(chunks) == PAYLOAD

    def test_read_past_the_end_returns_the_tail(self, make_store, root):
        store = make_store()
        artifact_id = store.put(_write(root), "audio/wav")

        assert store.read_chunk(artifact_id, len(PAYLOAD) - 3, 100) == PAYLOAD[-3:]

    @pytest.mark.parametrize("offset", [len(PAYLOAD), len(PAYLOAD) + 1, 10**12])
    def test_offset_at_or_past_the_end_returns_empty_bytes(self, make_store, root, offset):
        store = make_store()
        artifact_id = store.put(_write(root), "audio/wav")

        assert store.read_chunk(artifact_id, offset, 10) == b""

    def test_zero_length_returns_empty_bytes(self, make_store, root):
        store = make_store()
        artifact_id = store.put(_write(root), "audio/wav")

        assert store.read_chunk(artifact_id, 0, 0) == b""

    def test_a_full_size_chunk_is_allowed(self, make_store, root):
        store = make_store()
        data = b"x" * (MAX_CHUNK_BYTES + 5)
        artifact_id = store.put(_write(root, data=data), "audio/wav")

        assert len(store.read_chunk(artifact_id, 0, MAX_CHUNK_BYTES)) == MAX_CHUNK_BYTES

    def test_an_empty_file_is_stored_with_length_zero(self, make_store, root):
        store = make_store()
        artifact_id = store.put(_write(root, data=b""), "audio/wav")

        assert store.info(artifact_id).byte_length == 0
        assert store.read_chunk(artifact_id, 0, 10) == b""


class TestUnknownIds:
    """AC-S2: an id that was never issued, or has expired, is INVALID_PARAMETER; ids are never paths."""

    @pytest.mark.parametrize(
        "artifact_id",
        ["nope", "", "../x", "../../etc/passwd", "/etc/passwd", "track.wav", "C:\\x", None, 7, ["a"]],
    )
    def test_unknown_ids_are_invalid_parameter(self, make_store, root, artifact_id):
        store = make_store()
        store.put(_write(root), "audio/wav")

        for call in (lambda: store.info(artifact_id), lambda: store.read_chunk(artifact_id, 0, 10)):
            with pytest.raises(ArtifactError) as excinfo:
                call()
            assert _error(excinfo)["error_code"] == "INVALID_PARAMETER"

    def test_the_file_path_itself_is_not_an_id(self, make_store, root):
        store = make_store()
        path = _write(root)
        store.put(path, "audio/wav")

        with pytest.raises(ArtifactError):
            store.read_chunk(str(path), 0, 10)

    def test_the_error_does_not_echo_the_id_or_reveal_paths(self, make_store, root):
        store = make_store()
        store.put(_write(root), "audio/wav")

        with pytest.raises(ArtifactError) as excinfo:
            store.read_chunk("../secret-name", 0, 10)

        payload = _error(excinfo)
        assert "secret-name" not in str(payload)
        assert str(root) not in str(payload)
        assert payload["hint"]

    def test_artifact_errors_are_processing_errors(self):
        assert issubclass(ArtifactError, ProcessingError)


class TestChunkLimits:
    @pytest.mark.parametrize("offset, length", [(-1, 10), (0, -1), (-5, -5)])
    def test_negative_offset_or_length_is_invalid_parameter(self, make_store, root, offset, length):
        store = make_store()
        artifact_id = store.put(_write(root), "audio/wav")

        with pytest.raises(ArtifactError) as excinfo:
            store.read_chunk(artifact_id, offset, length)

        assert _error(excinfo)["error_code"] == "INVALID_PARAMETER"

    def test_length_over_the_limit_names_the_limit_in_the_hint(self, make_store, root):
        store = make_store()
        artifact_id = store.put(_write(root), "audio/wav")

        with pytest.raises(ArtifactError) as excinfo:
            store.read_chunk(artifact_id, 0, MAX_CHUNK_BYTES + 1)

        payload = _error(excinfo)
        assert payload["error_code"] == "INVALID_PARAMETER"
        assert str(MAX_CHUNK_BYTES) in payload["hint"]

    @pytest.mark.parametrize("offset, length", [(0.5, 10), (0, "10"), (True, 10), (0, None)])
    def test_non_integer_offset_or_length_is_invalid_parameter(self, make_store, root, offset, length):
        store = make_store()
        artifact_id = store.put(_write(root), "audio/wav")

        with pytest.raises(ArtifactError) as excinfo:
            store.read_chunk(artifact_id, offset, length)

        assert _error(excinfo)["error_code"] == "INVALID_PARAMETER"

    def test_max_chunk_is_one_mebibyte(self):
        assert MAX_CHUNK_BYTES == 1_048_576


class TestExpiry:
    def test_entry_is_readable_until_the_ttl(self, make_store, root, clock):
        store = make_store(ttl_seconds=60)
        artifact_id = store.put(_write(root), "audio/wav")

        clock.advance(59.9)

        assert store.info(artifact_id).byte_length == len(PAYLOAD)

    def test_entry_expires_after_the_ttl(self, make_store, root, clock):
        store = make_store(ttl_seconds=60)
        artifact_id = store.put(_write(root), "audio/wav")

        clock.advance(60)

        with pytest.raises(ArtifactError) as excinfo:
            store.read_chunk(artifact_id, 0, 10)
        assert _error(excinfo)["error_code"] == "INVALID_PARAMETER"

    def test_reads_do_not_extend_the_ttl(self, make_store, root, clock):
        store = make_store(ttl_seconds=60)
        artifact_id = store.put(_write(root), "audio/wav")

        clock.advance(40)
        store.read_chunk(artifact_id, 0, 10)
        clock.advance(40)

        with pytest.raises(ArtifactError):
            store.info(artifact_id)

    def test_oldest_entries_are_evicted_past_max_entries(self, make_store, root, clock):
        store = make_store(max_entries=2)
        path = _write(root)
        first = store.put(path, "audio/wav")
        clock.advance(1)
        second = store.put(path, "audio/wav")
        clock.advance(1)
        third = store.put(path, "audio/wav")

        with pytest.raises(ArtifactError):
            store.info(first)
        assert store.info(second).artifact_id == second
        assert store.info(third).artifact_id == third

    def test_expired_entries_do_not_count_towards_max_entries(self, make_store, root, clock):
        store = make_store(ttl_seconds=10, max_entries=2)
        path = _write(root)
        store.put(path, "audio/wav")
        clock.advance(5)
        kept = store.put(path, "audio/wav")
        clock.advance(6)  # the first has expired, the second has not
        newest = store.put(path, "audio/wav")

        assert store.info(kept).artifact_id == kept
        assert store.info(newest).artifact_id == newest

    @pytest.mark.parametrize("kwargs", [{"ttl_seconds": 0}, {"ttl_seconds": -1}, {"max_entries": 0}])
    def test_rejects_unusable_limits(self, make_store, kwargs):
        with pytest.raises(ValueError):
            make_store(**kwargs)

    def test_rejects_an_empty_kind(self, make_store, root):
        with pytest.raises(ValueError):
            make_store().put(_write(root), "")


class TestFileStorePut:
    def test_a_file_outside_the_root_is_refused(self, root, tmp_path, clock):
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        store = FileArtifactStore(root, clock=clock)

        with pytest.raises(ArtifactError) as excinfo:
            store.put(_write(outside), "audio/wav")

        assert _error(excinfo)["error_code"] == "INVALID_PARAMETER"

    def test_a_dotdot_path_that_escapes_the_root_is_refused(self, root, tmp_path, clock):
        _write(tmp_path, "escape.wav")
        store = FileArtifactStore(root, clock=clock)

        with pytest.raises(ArtifactError):
            store.put(root / ".." / "escape.wav", "audio/wav")

    def test_a_symlink_to_a_file_inside_the_root_is_refused(self, root, clock):
        real = _write(root)
        link = root / "alias.wav"
        link.symlink_to(real)
        store = FileArtifactStore(root, clock=clock)

        with pytest.raises(ArtifactError) as excinfo:
            store.put(link, "audio/wav")

        assert _error(excinfo)["error_code"] == "INVALID_PARAMETER"

    def test_a_symlink_pointing_out_of_the_root_is_refused(self, root, tmp_path, clock):
        link = root / "link.wav"
        link.symlink_to(_write(tmp_path, "secret.wav"))
        store = FileArtifactStore(root, clock=clock)

        with pytest.raises(ArtifactError):
            store.put(link, "audio/wav")

    def test_a_file_under_a_symlinked_folder_is_refused(self, root, tmp_path, clock):
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        _write(outside)
        (root / "audio").symlink_to(outside)
        store = FileArtifactStore(root, clock=clock)

        with pytest.raises(ArtifactError):
            store.put(root / "audio" / "track.wav", "audio/wav")

    def test_a_missing_file_is_file_not_found(self, root, clock):
        store = FileArtifactStore(root, clock=clock)

        with pytest.raises(ArtifactError) as excinfo:
            store.put(root / "missing.wav", "audio/wav")

        assert _error(excinfo)["error_code"] == "FILE_NOT_FOUND"

    def test_a_directory_is_file_not_found(self, root, clock):
        (root / "folder").mkdir()
        store = FileArtifactStore(root, clock=clock)

        with pytest.raises(ArtifactError) as excinfo:
            store.put(root / "folder", "audio/wav")

        assert _error(excinfo)["error_code"] == "FILE_NOT_FOUND"

    def test_a_relative_path_resolves_against_the_root(self, root, clock):
        (root / "audio").mkdir()
        _write(root / "audio")
        store = FileArtifactStore(root, clock=clock)

        artifact_id = store.put(Path("audio/track.wav"), "audio/wav")

        assert store.read_chunk(artifact_id, 0, 4) == PAYLOAD[:4]

    def test_default_root_is_the_output_root(self, root, clock):
        store = FileArtifactStore(clock=clock)

        artifact_id = store.put(_write(root), "audio/wav")

        assert store.info(artifact_id).byte_length == len(PAYLOAD)

    def test_default_root_refuses_files_outside_the_output_root(self, root, tmp_path, clock):
        store = FileArtifactStore(clock=clock)

        with pytest.raises(ArtifactError):
            store.put(_write(tmp_path, "outside.wav"), "audio/wav")


class TestFileStoreReadRechecks:
    """The file is re-checked on every read, so a swap after ``put`` never leaks another file."""

    def _stored(self, root, clock):
        store = FileArtifactStore(root, clock=clock)
        path = _write(root)
        return store, path, store.put(path, "audio/wav")

    def _assert_gone(self, store, artifact_id):
        with pytest.raises(ArtifactError) as excinfo:
            store.read_chunk(artifact_id, 0, 10)
        assert _error(excinfo)["error_code"] == "INVALID_PARAMETER"
        with pytest.raises(ArtifactError):
            store.info(artifact_id)  # the entry is dropped

    def test_a_deleted_file_is_no_longer_available(self, root, clock):
        store, path, artifact_id = self._stored(root, clock)
        path.unlink()

        self._assert_gone(store, artifact_id)

    def test_a_file_replaced_by_a_symlink_is_refused(self, root, tmp_path, clock):
        store, path, artifact_id = self._stored(root, clock)
        secret = _write(tmp_path, "secret.wav", b"SECRET" * 100)
        path.unlink()
        path.symlink_to(secret)

        self._assert_gone(store, artifact_id)

    def test_a_parent_folder_replaced_by_a_symlink_is_refused(self, root, tmp_path, clock):
        store = FileArtifactStore(root, clock=clock)
        folder = root / "audio"
        folder.mkdir()
        artifact_id = store.put(_write(folder), "audio/wav")
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        _write(outside, data=b"SECRET" * 100)
        (folder / "track.wav").unlink()
        folder.rmdir()
        folder.symlink_to(outside)

        self._assert_gone(store, artifact_id)

    def test_a_file_replaced_by_another_file_of_the_same_size_is_refused(self, root, clock):
        store, path, artifact_id = self._stored(root, clock)
        replacement = _write(root, "other.wav", b"S" * len(PAYLOAD))
        os.replace(replacement, path)

        self._assert_gone(store, artifact_id)

    def test_the_same_file_moved_out_and_linked_back_is_refused(self, root, tmp_path, clock):
        """Same inode and size, so only the symlink checks stand between the read and the file."""
        store, path, artifact_id = self._stored(root, clock)
        moved = tmp_path / "moved.wav"
        os.rename(path, moved)
        path.symlink_to(moved)

        self._assert_gone(store, artifact_id)

    def test_the_same_folder_moved_out_and_linked_back_is_refused(self, root, tmp_path, clock):
        store = FileArtifactStore(root, clock=clock)
        folder = root / "audio"
        folder.mkdir()
        artifact_id = store.put(_write(folder), "audio/wav")
        moved = tmp_path / "moved-audio"
        os.rename(folder, moved)
        folder.symlink_to(moved)

        self._assert_gone(store, artifact_id)

    def test_a_file_that_changed_size_is_refused(self, root, clock):
        store, path, artifact_id = self._stored(root, clock)
        with path.open("ab") as handle:
            handle.write(b"more")

        self._assert_gone(store, artifact_id)


class TestInMemoryStore:
    def test_put_bytes_stores_data_without_a_file(self, clock):
        store = InMemoryArtifactStore(clock=clock)

        artifact_id = store.put_bytes(b"abcdef", "image/svg+xml")

        assert store.info(artifact_id) == ArtifactInfo(artifact_id, "image/svg+xml", 6)
        assert store.read_chunk(artifact_id, 2, 3) == b"cde"

    def test_put_copies_the_file_so_later_changes_do_not_matter(self, root, clock):
        store = InMemoryArtifactStore(clock=clock)
        path = _write(root)
        artifact_id = store.put(path, "audio/wav")
        path.unlink()

        assert store.read_chunk(artifact_id, 0, 4) == PAYLOAD[:4]


class TestChunkPayload:
    def test_shape_for_a_middle_chunk(self, make_store, root):
        store = make_store()
        artifact_id = store.put(_write(root), "audio/wav")

        payload = chunk_payload(store, artifact_id, 100, 50)

        assert payload == {
            "artifact_id": artifact_id,
            "offset": 100,
            "length": 50,
            "byte_length": len(PAYLOAD),
            "eof": False,
            "data_b64": base64.b64encode(PAYLOAD[100:150]).decode("ascii"),
        }

    def test_the_last_chunk_is_short_and_flags_eof(self, make_store, root):
        store = make_store()
        artifact_id = store.put(_write(root), "audio/wav")

        payload = chunk_payload(store, artifact_id, len(PAYLOAD) - 10, 1000)

        assert payload["length"] == 10
        assert payload["eof"] is True
        assert base64.b64decode(payload["data_b64"]) == PAYLOAD[-10:]

    def test_past_the_end_is_an_empty_eof_chunk(self, make_store, root):
        store = make_store()
        artifact_id = store.put(_write(root), "audio/wav")

        payload = chunk_payload(store, artifact_id, len(PAYLOAD) + 5, 10)

        assert payload["length"] == 0 and payload["data_b64"] == "" and payload["eof"] is True

    def test_a_loop_until_eof_reassembles_the_file(self, make_store, root):
        """AC-S3, as a UI would fetch it."""
        store = make_store()
        artifact_id = store.put(_write(root), "audio/wav")
        received, offset = b"", 0
        while True:
            payload = chunk_payload(store, artifact_id, offset, 4096)
            received += base64.b64decode(payload["data_b64"])
            offset += payload["length"]
            if payload["eof"]:
                break

        assert received == PAYLOAD

    def test_errors_propagate_for_unknown_ids(self, make_store):
        with pytest.raises(ArtifactError) as excinfo:
            chunk_payload(make_store(), "../x", 0, 10)

        assert _error(excinfo)["error_code"] == "INVALID_PARAMETER"
