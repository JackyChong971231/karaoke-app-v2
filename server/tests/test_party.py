"""Spec examples as tests on the pure reducer. No server, no browser, no mocks: inputs in, state out.

The cases are the spec (00-product.md "Queue fairness", "Restart the app", "Fill an empty queue",
"Song preparation").
"""

from __future__ import annotations

import dataclasses

from hypothesis import given, settings
from hypothesis import strategies as st

from karaoke.core import ArtistId, ArtistRef, SingerId, SongId, SongMeta
from karaoke.party import (
    Accepted, AwaitingRestartChoice, Before, DurableSnapshot, End, EntryId, Filler, FillerPicked, FromQueue, Front,
    Hello, Idle, Input, MoveEntry, PartyState, PlayId, Playing, QueueSong, Rejected, RemoveEntry, Rename,
    ResolveRestart, Running, SavedEntry, SetAvOffset, SetKey, SetPaused, SetVocal, Settings, Skip, SongReady,
    TrackEnded, TrackFailed, TvPresence, durable, filler_request, initial_state, preparation_demand, reduce,
)

A, B, C, D = (SingerId(x) for x in "ABCD")


def song(n: str) -> SongMeta:
    return SongMeta(SongId(f"vid{n}"), f"Song {n}", ArtistRef(ArtistId("UCx"), "Artist"), 200.0)


def run(state: PartyState, *inputs: Input) -> PartyState:
    for inp in inputs:
        step = reduce(state, inp)
        assert step.outcome == Accepted(), (inp, step.outcome)
        state = step.state
    return state


def party() -> PartyState:
    """initial_state(None) with singers A, B, C, D said Hello, TV connected."""
    return run(initial_state(None), *(Hello(s, s) for s in (A, B, C, D)), TvPresence(True))


def queue_as(state: PartyState, *singers_in_order: str) -> PartyState:
    """Each letter queues a fresh not-yet-ready song (so nothing starts playing and the queue is observable)."""
    for letter in singers_in_order:
        state = run(state, QueueSong(SingerId(letter), song(f"q{state.next_entry_id}")))
    return state


def order(state: PartyState) -> str:
    """Queue as singer letters, e.g. 'ABCABBB'."""
    return "".join(e.singer for e in state.queue)


def playing(state: PartyState) -> Playing:
    assert isinstance(state.now, Playing)
    return state.now


def test_fairness_example_from_user() -> None:
    s = queue_as(party(), *"ABBBBAC")
    assert order(s) == "ABCABBB"
    s = queue_as(s, "C")
    assert order(s) == "ABCABCBB"


def test_fairness_history_example() -> None:
    """A has sung 3 tonight; D joins. D's round 1 goes before A's round 4."""
    s = party()
    for n in range(3):
        s = run(s, SongReady(song(f"a{n}").id), QueueSong(A, song(f"a{n}")))
        s = run(s, TrackEnded(playing(s).play_id))
    assert s.fairness.sung[A] == 3 and isinstance(s.now, Idle)
    s = queue_as(s, "A", "D")
    assert order(s) == "DA"
    assert [e.round for e in s.queue] == [1, 4]


def test_song_counts_as_sung_when_it_starts() -> None:
    s = run(party(), SongReady(song("x").id), QueueSong(A, song("x")))
    assert s.fairness.sung == {A: 1}
    s = queue_as(s, "B", "A")
    assert order(s) == "BA"
    assert [e.round for e in s.queue] == [1, 2]


def test_manual_move_is_kept_and_new_songs_are_still_placed_fairly() -> None:
    s = queue_as(party(), *"ABB")
    last_b = s.queue[-1].id
    s = run(s, MoveEntry(C, last_b, Front()))
    assert order(s) == "BAB"
    s = queue_as(s, "C")
    assert order(s) == "BABC", "C1 goes right after the last entry with a smaller key (A1), moves are not undone"


def test_move_before_and_end_and_unknown_entry() -> None:
    s = queue_as(party(), *"ABC")
    a, b, c = (e.id for e in s.queue)
    s = run(s, MoveEntry(A, c, Before(a)))
    assert order(s) == "CAB"
    s = run(s, MoveEntry(A, c, End()))
    assert order(s) == "ABC"
    assert reduce(s, MoveEntry(A, c, Before(c))).state is s
    step = reduce(s, MoveEntry(A, EntryId(999), Front()))
    assert step.outcome == Rejected("unknown_entry") and step.state is s
    step = reduce(s, MoveEntry(A, a, Before(EntryId(999))))
    assert step.outcome == Rejected("unknown_entry")


def test_remove_twice_is_unknown_entry() -> None:
    s = queue_as(party(), *"AB")
    a = s.queue[0].id
    s = run(s, RemoveEntry(B, a))
    assert order(s) == "B"
    assert reduce(s, RemoveEntry(C, a)).outcome == Rejected("unknown_entry")


def test_unready_song_keeps_front_place_while_next_ready_song_plays() -> None:
    s = queue_as(party(), "A")
    s = run(s, QueueSong(B, song("y")))
    assert isinstance(s.now, Idle)
    s = run(s, SongReady(song("y").id))
    assert playing(s).song == song("y")
    assert order(s) == "A"
    a_song = s.queue[0].song
    s = run(s, SongReady(a_song.id), TrackEnded(playing(s).play_id))
    assert playing(s).song == a_song and order(s) == ""


def test_double_skip_with_same_play_id_skips_one_song() -> None:
    s = party()
    for n in range(3):
        s = run(s, SongReady(song(str(n)).id))
    s = run(s, QueueSong(A, song("0")), QueueSong(B, song("1")), QueueSong(C, song("2")))
    current = playing(s).play_id
    s = run(s, Skip(A, current))
    assert playing(s).song == song("1")
    step = reduce(s, Skip(B, current))
    assert step.outcome == Rejected("stale_play") and step.state is s
    assert order(s) == "C"


def test_late_track_ended_from_reloaded_tv_is_stale() -> None:
    s = run(party(), SongReady(song("0").id), SongReady(song("1").id), QueueSong(A, song("0")), QueueSong(B, song("1")))
    first = playing(s).play_id
    s = run(s, TrackEnded(first))
    assert reduce(s, TrackEnded(first)).outcome == Rejected("stale_play")
    assert reduce(s, TrackFailed(first, "decode")).outcome == Rejected("stale_play")


def test_playback_setters_are_absolute_and_validated() -> None:
    s = run(party(), SongReady(song("0").id), QueueSong(A, song("0")))
    p = playing(s).play_id
    s = run(s, SetPaused(B, p, True), SetPaused(C, p, True), SetKey(A, p, 3))
    assert playing(s).paused and playing(s).semitones == 3
    assert reduce(s, SetKey(A, p, 7)).outcome == Rejected("invalid_value")
    assert reduce(s, SetVocal(A, 1.5)).outcome == Rejected("invalid_value")
    assert reduce(s, SetVocal(A, float("nan"))).outcome == Rejected("invalid_value")
    assert reduce(s, SetAvOffset(A, -0.1)).outcome == Rejected("invalid_value")
    s = run(s, SetVocal(A, 0.4), SetAvOffset(A, 0.2))
    assert s.settings == Settings(vocal_level=0.4, av_offset_s=0.2)
    assert reduce(party(), Skip(A, PlayId(1))).outcome == Rejected("nothing_playing")


def test_key_resets_and_vocal_level_persists_across_songs() -> None:
    s = run(party(), SongReady(song("0").id), SongReady(song("1").id), QueueSong(A, song("0")), QueueSong(B, song("1")))
    p = playing(s).play_id
    s = run(s, SetKey(A, p, -2), SetVocal(A, 0.7), TrackEnded(p))
    assert playing(s).semitones == 0 and s.settings.vocal_level == 0.7


def test_names_and_unknown_singer() -> None:
    s = party()
    assert reduce(s, QueueSong(SingerId("Z"), song("0"))).outcome == Rejected("unknown_singer")
    assert reduce(s, Rename(A, "   ")).outcome == Rejected("invalid_value")
    assert reduce(s, Rename(A, "x" * 33)).outcome == Rejected("invalid_value")
    s = run(s, Rename(A, "  Amy "))
    assert s.singers[A] == "Amy"


def test_filler_plays_when_idle_and_is_not_interrupted_by_a_ready_song() -> None:
    s = party()
    req = filler_request(s)
    assert req is not None and req.token == s.next_play_id
    s = run(s, FillerPicked(req.token, song("f")))
    assert playing(s).origin == Filler() and s.recent_fillers == (song("f").id,)
    assert filler_request(s) is None
    s = run(s, QueueSong(A, song("0")), SongReady(song("0").id))
    assert playing(s).origin == Filler(), "a newly ready song does not interrupt the filler"
    assert order(s) == "A"
    assert s.fairness.sung == {}, "a filler never counts toward fairness"
    s = run(s, Skip(B, playing(s).play_id))
    assert playing(s).song == song("0") and isinstance(playing(s).origin, FromQueue)


def test_filler_needs_a_connected_tv_and_no_ready_song() -> None:
    s = run(initial_state(None), Hello(A, "A"))
    assert filler_request(s) is None
    s = run(s, TvPresence(True))
    assert filler_request(s) is not None
    s = queue_as(s, "A")
    req = filler_request(s)
    assert req is not None and s.queue[0].song.id in req.avoid, "an unready queued song is never picked as filler"


def test_filler_after_end_avoids_recent_fillers() -> None:
    s = party()
    s = run(s, FillerPicked(s.next_play_id, song("f")))
    s = run(s, TrackEnded(playing(s).play_id))
    req = filler_request(s)
    assert req is not None and song("f").id in req.avoid


def test_stale_filler_pick_is_dropped() -> None:
    s = party()
    req = filler_request(s)
    assert req is not None
    s = run(s, SongReady(song("0").id), QueueSong(A, song("0")))
    assert playing(s).song == song("0")
    step = reduce(s, FillerPicked(req.token, song("f")))
    assert step.outcome == Accepted() and step.state is s


def saved(*letters: str) -> DurableSnapshot:
    return DurableSnapshot(
        queue=tuple(SavedEntry(song(f"s{i}"), SingerId(x), f"name{x}") for i, x in enumerate(letters)),
        settings=Settings(vocal_level=0.3, av_offset_s=0.1),
    )


def test_restart_keep_keeps_order_and_resets_fairness() -> None:
    """Saved A B B; keep -> same order, rounds renumbered 1,1,2; a new C song goes after B1 (round 1, joined 3rd)."""
    s = initial_state(saved("A", "B", "B"))
    assert isinstance(s.phase, AwaitingRestartChoice) and s.queue == ()
    assert s.settings == Settings(vocal_level=0.3, av_offset_s=0.1)
    s = run(s, Hello(C, "Cat"))
    assert reduce(s, QueueSong(C, song("c"))).outcome == Rejected("awaiting_restart_choice")
    s = run(s, ResolveRestart(keep=True))
    assert order(s) == "ABB" and [e.round for e in s.queue] == [1, 1, 2]
    assert s.fairness.join_order == (A, B) and s.fairness.sung == {}
    assert s.singers[A] == "nameA" and s.singers[C] == "Cat"
    s = queue_as(s, "C")
    assert order(s) == "ABCB"
    assert len({e.id for e in s.queue}) == 4


def test_restart_new_starts_empty() -> None:
    s = run(initial_state(saved("A", "B")), ResolveRestart(keep=False))
    assert isinstance(s.phase, Running) and s.queue == ()
    assert durable(s).queue == ()


def test_restart_first_answer_wins() -> None:
    s = run(initial_state(saved("A", "B")), ResolveRestart(keep=False))
    step = reduce(s, ResolveRestart(keep=True))
    assert step.outcome == Rejected("already_resolved") and step.state is s


def test_crash_during_prompt_keeps_the_offer() -> None:
    snap = saved("A", "B")
    assert durable(initial_state(snap)) == snap


def test_durable_snapshot_has_no_fairness() -> None:
    assert {f.name for f in dataclasses.fields(DurableSnapshot)} == {"queue", "settings"}
    s = run(party(), SongReady(song("0").id), QueueSong(A, song("0")))
    s = queue_as(s, "B")
    snap = durable(s)
    assert [e.singer for e in snap.queue] == [A, B], "the now-playing queued song is saved at the front"
    restarted = run(initial_state(snap), ResolveRestart(keep=True))
    assert restarted.fairness.sung == {}


def test_preparation_demand_is_queue_order_deduplicated() -> None:
    s = run(party(), QueueSong(A, song("0")), QueueSong(B, song("1")), QueueSong(C, song("0")))
    assert preparation_demand(s) == (song("0"), song("1"))
    s = run(s, MoveEntry(A, s.queue[1].id, Front()))
    assert preparation_demand(s)[0] == song("1"), "'play next' also moves preparation forward"


# ---- invariants over random input sequences ------------------------------------------------------

SINGERS = [A, B, C, D, SingerId("Z")]
SONGS = [song(str(n)) for n in range(5)]
entry_ids = st.builds(EntryId, st.integers(1, 12))
play_ids = st.builds(PlayId, st.integers(1, 8))
singers = st.sampled_from(SINGERS)
positions = st.one_of(st.just(Front()), st.just(End()), st.builds(Before, entry_ids))

inputs: st.SearchStrategy[Input] = st.one_of(
    st.builds(Hello, singers, st.sampled_from(["Amy", "Bo", "", "x" * 40])),
    st.builds(Rename, singers, st.sampled_from(["Cy", " "])),
    st.builds(QueueSong, singers, st.sampled_from(SONGS)),
    st.builds(RemoveEntry, singers, entry_ids),
    st.builds(MoveEntry, singers, entry_ids, positions),
    st.builds(SetPaused, singers, play_ids, st.booleans()),
    st.builds(Skip, singers, play_ids),
    st.builds(SetKey, singers, play_ids, st.integers(-8, 8)),
    st.builds(SetVocal, singers, st.floats(-0.5, 1.5)),
    st.builds(SetAvOffset, singers, st.floats(-0.5, 1.5)),
    st.builds(ResolveRestart, st.booleans()),
    st.builds(TrackEnded, play_ids),
    st.builds(TrackFailed, play_ids, st.just("decode")),
    st.builds(SongReady, st.sampled_from([s.id for s in SONGS])),
    st.builds(FillerPicked, play_ids, st.sampled_from(SONGS)),
    st.builds(TvPresence, st.booleans()),
)
starts = st.sampled_from([None, saved(), saved("A", "B", "B")])


def check_invariants(s: PartyState) -> None:
    ids = [e.id for e in s.queue]
    playing_entry = s.now.origin.entry if isinstance(s.now, Playing) and isinstance(s.now.origin, FromQueue) else None
    all_ids = ids + ([playing_entry.id] if playing_entry else [])
    assert len(set(all_ids)) == len(all_ids), "entry ids are unique"
    assert all(i < s.next_entry_id for i in all_ids)
    assert playing_entry is None or playing_entry not in s.queue, "now-playing entry is not in the queue"
    assert all(e.singer in s.fairness.join_order for e in s.queue), "every queued singer has joined"
    if isinstance(s.phase, AwaitingRestartChoice):
        assert s.queue == () and isinstance(s.now, Idle)
    if isinstance(s.phase, Running) and isinstance(s.now, Idle):
        assert not any(e.song.id in s.ready for e in s.queue), "an idle TV never leaves a ready song waiting"
    if isinstance(s.now, Playing):
        assert s.now.play_id < s.next_play_id


def relative_order_kept(before: PartyState, after: PartyState) -> bool:
    old = [e.id for e in before.queue]
    new = [e.id for e in after.queue]
    return [i for i in old if i in new] == [i for i in new if i in old]


@settings(max_examples=300, deadline=None)
@given(starts, st.lists(inputs, max_size=40))
def test_any_input_sequence_keeps_invariants(start: DurableSnapshot | None, seq: list[Input]) -> None:
    """Entry ids unique; now-playing entry not in queue; every queued singer joined; rejected inputs leave
    state identical; only MoveEntry reorders existing entries; a double skip skips one song."""
    s = initial_state(start)
    check_invariants(s)
    for inp in seq:
        step = reduce(s, inp)
        if isinstance(step.outcome, Rejected):
            assert step.state is s
        if not isinstance(inp, MoveEntry):
            assert relative_order_kept(s, step.state)
        s = step.state
        check_invariants(s)
        if isinstance(s.now, Playing):
            once = reduce(s, Skip(A, s.now.play_id)).state
            twice = reduce(once, Skip(B, s.now.play_id))
            assert isinstance(twice.outcome, Rejected) and twice.state is once
