"""ScoreBook: the MusicXML behind each audio id, kept in step with the artifact store."""

import pytest
from sheet_music_mcp_core.artifacts import ArtifactError, InMemoryArtifactStore

from synth_mcp.scorebook import ScoreBook


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _book(store, **kwargs):
    return ScoreBook(lambda: store, **kwargs)


def _remember(store, book, xml="<score-partwise/>"):
    audio_id = store.put_bytes(b"RIFF", "audio/wav")
    book.remember(audio_id, xml)
    return audio_id


def test_returns_the_score_remembered_for_an_id():
    store = InMemoryArtifactStore()
    book = _book(store)
    audio_id = _remember(store, book, "<a/>")

    assert book.get(audio_id) == "<a/>"


@pytest.mark.parametrize("bad", ["nope", "", None, 7, "../../etc/passwd"])
def test_unknown_id_is_invalid_parameter(bad):
    with pytest.raises(ArtifactError) as caught:
        _book(InMemoryArtifactStore()).get(bad)

    assert caught.value.error_code == "INVALID_PARAMETER"


def test_an_id_the_store_knows_but_the_book_does_not_is_unknown():
    store = InMemoryArtifactStore()
    other_id = store.put_bytes(b"x", "audio/wav")

    with pytest.raises(ArtifactError) as caught:
        _book(store).get(other_id)

    assert caught.value.error_code == "INVALID_PARAMETER"


def test_expires_with_the_artifact():
    clock = Clock()
    store = InMemoryArtifactStore(ttl_seconds=10, clock=clock)
    book = _book(store)
    audio_id = _remember(store, book)

    clock.now = 10
    with pytest.raises(ArtifactError):
        book.get(audio_id)


def test_dropped_entries_are_forgotten_on_the_next_remember():
    clock = Clock()
    store = InMemoryArtifactStore(ttl_seconds=10, clock=clock)
    book = _book(store, ttl_seconds=10, clock=clock)
    for _ in range(3):
        _remember(store, book)

    clock.now = 20
    _remember(store, book)

    assert len(book) == 1


def test_never_holds_more_than_the_store_does():
    store = InMemoryArtifactStore(max_entries=2)
    book = _book(store, max_entries=2)

    ids = [_remember(store, book, f"<s{i}/>") for i in range(4)]

    assert len(book) == 2
    assert [book.get(i) for i in ids[2:]] == ["<s2/>", "<s3/>"]
    with pytest.raises(ArtifactError):
        book.get(ids[0])


def test_follows_a_replaced_store():
    first, second = InMemoryArtifactStore(), InMemoryArtifactStore()
    current = [first]
    book = ScoreBook(lambda: current[0])
    audio_id = _remember(first, book)

    current[0] = second

    with pytest.raises(ArtifactError):
        book.get(audio_id)
