"""The shell's pure and file-level pieces: store, journal, views, parse, and the schema export."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from karaoke import contract as c
from karaoke.core import ArtistId, ArtistRef, SingerId, SongId, SongMeta
from karaoke.party import (
    Before, DurableSnapshot, EntryId, FillerPicked, Hello, MoveEntry, PartyState, PlayId, QueueSong, ResolveRestart, SavedEntry,
    Settings, Skip, SongReady, TvPresence, initial_state, reduce,
)
from karaoke.shell import export_schema, parse, views
from karaoke.shell.journal import Journal, replay
from karaoke.shell.store import Store
from karaoke.songs.prepare import PrepStatus

A = SingerId("A")


def song(n: str) -> SongMeta:
    return SongMeta(SongId(f"vid{n}"), f"歌 {n}", ArtistRef(ArtistId("UCx"), "歌手"), 200.0)


def fold(*inputs: object, start: DurableSnapshot | None = None) -> PartyState:
    s = initial_state(start)
    for inp in inputs:
        s = reduce(s, inp).state  # type: ignore[arg-type]
    return s


def test_store_round_trips_and_survives_corruption(tmp_path: Path) -> None:
    store = Store(tmp_path / "party.json")
    assert store.load() is None
    snap = DurableSnapshot(queue=(SavedEntry(song("1"), A, "Amy"),), settings=Settings(0.5, 0.2))
    store.save(snap)
    assert Store(tmp_path / "party.json").load() == snap
    (tmp_path / "party.json").write_text("{not json", encoding="utf-8")
    assert store.load() is None
    assert [p.name.startswith("party.json.bad-") for p in tmp_path.iterdir()] == [True]


def test_journal_replays_to_the_same_state(tmp_path: Path) -> None:
    inputs = [Hello(A, "Amy"), TvPresence(True), QueueSong(A, song("1")), QueueSong(A, song("2")),
              MoveEntry(A, EntryId(2), Before(EntryId(1))),
              SongReady(song("2").id), Skip(A, PlayId(1)), FillerPicked(PlayId(2), song("3"))]
    journal = Journal(tmp_path / "j.jsonl")
    for inp in inputs:
        journal.append(inp)
    journal.close()
    assert replay(tmp_path / "j.jsonl", initial_state(None)) == fold(*inputs)


def test_views_merge_party_board_and_clock() -> None:
    s = fold(Hello(A, "Amy"), TvPresence(True), QueueSong(A, song("1")), QueueSong(A, song("2")), SongReady(song("2").id))
    board = {song("1").id: PrepStatus("separating", 0.5)}
    phone = views.phone_view(7, s, board, "cpu", frozenset({song("2").id}))
    assert phone.now is not None and phone.now.song.song_id == "vid2" and phone.now.lyrics_flagged
    assert phone.now.singer_name == "Amy" and not phone.now.is_filler
    assert phone.queue[0].readiness == c.PreparingState(kind="preparing", stage="separating", progress=0.5)
    tv = views.tv_view(7, s, {phone.now.play_id: 42.5}, "http://x/", frozenset())
    assert tv.play is not None and tv.play.resume_at_s == 42.5
    assert tv.up_next == c.UpNext(title="歌 1", singer_name="Amy", ready=False)
    wire = json.loads(phone.model_dump_json(by_alias=True))
    assert wire["now"]["playId"] == 1 and wire["queue"][0]["readiness"]["kind"] == "preparing"


def test_failed_preparation_shows_its_reason() -> None:
    s = fold(Hello(A, "Amy"), QueueSong(A, song("1")))
    r = views.readiness(song("1").id, s, {song("1").id: PrepStatus("failed", None, "cant_download")})
    assert r == c.FailedState(kind="failed", reason="cant_download")


def test_restart_offer_shows_on_both_views() -> None:
    s = initial_state(DurableSnapshot((SavedEntry(song("1"), A, "Amy"),), Settings()))
    assert views.phone_view(1, s, {}, "cpu", frozenset()).restart_offer == views.tv_view(1, s, {}, "u", frozenset()).restart_offer
    s = reduce(s, ResolveRestart(True)).state
    assert views.phone_view(1, s, {}, "cpu", frozenset()).restart_offer is None


def test_parse_binds_sender_and_never_trusts_phone_metadata() -> None:
    class NoLibrary:
        def get(self, song: SongId) -> None:
            return None

    class NoPicks:
        def pick(self, pick: str) -> None:
            return None

    lib, cat = NoLibrary(), NoPicks()
    queue = c.QueueLibraryCmd(kind="queueLibrary", song_id="nope")
    assert parse.phone_input(queue, A, lib, cat) == parse.Unresolvable("unknown_entry")  # type: ignore[arg-type]
    pick = c.QueuePickCmd(kind="queuePick", pick_id="gone")
    assert parse.phone_input(pick, A, lib, cat) == parse.Unresolvable("pick_expired")  # type: ignore[arg-type]
    skip = c.SkipCmd(kind="skip", play_id=4)
    assert parse.phone_input(skip, A, lib, cat) == Skip(A, 4)  # type: ignore[arg-type,comparison-overlap]


def test_wire_parses_camel_case_commands() -> None:
    from pydantic import TypeAdapter

    msg = TypeAdapter(c.ClientMessage).validate_json(
        '{"kind":"phoneCommand","requestId":3,"command":{"kind":"move","entryId":5,"to":{"at":"before","entryId":2}}}')
    assert isinstance(msg, c.PhoneCommandMsg)
    assert parse.phone_input(msg.command, A, None, None) == MoveEntry(A, 5, Before(2))  # type: ignore[arg-type]


def test_schema_export_is_stable_and_carries_the_protocol(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "schema.json"
    monkeypatch.setattr("sys.argv", ["export_schema", "--out", str(out)])
    export_schema.main()
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["x-protocol"] == export_schema.protocol_hash()
    assert "ServerHello" in doc["$defs"] and list(doc["$defs"]) == sorted(doc["$defs"])
    assert doc["$defs"]["PhoneView"]["properties"].keys() >= {"rev", "restartOffer", "tvConnected"}
