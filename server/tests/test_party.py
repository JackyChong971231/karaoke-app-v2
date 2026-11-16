"""Spec examples as tests on the pure reducer. No server, no browser, no mocks: inputs in, state out.

The cases are the spec (00-product.md "Queue fairness", "Restart the app", "Fill an empty queue",
"Song preparation").
"""

from __future__ import annotations

import dataclasses
import random

from hypothesis import given, settings
from hypothesis import strategies as st

from karaoke.core import ArtistId, ArtistRef, SingerId, SongId, SongMeta
from karaoke.party import (
    Accepted, AwaitingRestartChoice, Before, DurableSnapshot, End, EntryId, Filler, FillerPicked, FromQueue, Front,
    Hello, Idle, Input, MoveEntry, PartyState, PlayId, Playing, QueueSong, Rejected, RemoveEntry, Rename,
    ResolveRestart, Running, SavedEntry, Seek, SeekTo, SetAvOffset, SetKey, SetPaused, SetVocal, SetVocalOn, Settings, Skip,
    SongReady, StepKey, TrackEnded, TrackFailed, TvPresence, durable, filler_request, initial_state, preparation_demand, reduce,
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


def test_fairness_example_from_user_2026_11_12() -> None:
    """A has 2 songs queued. B's song goes after A's first. A's third goes to the back. C's goes after B."""
    s = queue_as(party(), *"AA")
    s = queue_as(s, "B")
    assert order(s) == "ABA"
    s = queue_as(s, "A")
    assert order(s) == "ABAA"
    s = queue_as(s, "C")
    assert order(s) == "ABCAA"


def test_each_song_keeps_the_name_it_was_queued_with_and_fairness_ignores_names() -> None:
    s = run(party(), QueueSong(A, song("1"), "Amy"), Rename(A, "Not Amy"), QueueSong(A, song("2"), "Not Amy"))
    s = run(s, QueueSong(B, song("3")))
    assert [e.singer_name for e in s.queue] == ["Amy", "B", "Not Amy"]
    assert order(s) == "ABA", "a rename does not make A a new singer"
    assert [e.singer_name for e in durable(s).queue] == ["Amy", "B", "Not Amy"]


def sing(state: PartyState, *singers_in_order: str) -> PartyState:
    """Each letter sings one song start to finish (queued ready, played, ended)."""
    for letter in singers_in_order:
        m = song(f"sung{state.next_entry_id}")
        state = run(state, SongReady(m.id), QueueSong(SingerId(letter), m))
        state = run(state, TrackEnded(playing(state).play_id))
    return state


def test_screenshot_example_2026_11_15_history_earns_no_extra_turns() -> None:
    """Jacky sang 4, Beauty 3, K 1, ooo 2. Then J K K B O O K B queue: a plain rotation, never K K."""
    s = run(initial_state(None), *(Hello(SingerId(x), x) for x in "JBKO"), TvPresence(True))
    s = sing(s, *"JBKOJBOJBJ")
    assert isinstance(s.now, Idle) and s.queue == ()
    s = queue_as(s, *"JKKBOOKB")
    assert order(s) == "KBOJKBOK", "Jacky sang the last song, so Jacky waits behind the others"


def test_singer_of_the_song_playing_now_goes_to_the_back() -> None:
    s = run(party(), SongReady(song("x").id), QueueSong(A, song("x")))
    s = queue_as(s, "A", "B")
    assert order(s) == "BA", "A is singing now, so A has had this turn"
    s = queue_as(s, "B", "C")
    assert order(s) == "BCAB"


def test_removing_a_song_rebuilds_the_rotation() -> None:
    s = queue_as(party(), *"ABCABC")
    s = run(s, RemoveEntry(A, s.queue[1].id))
    assert order(s) == "ACBAC", "B, whose first song left, now waits behind C"
    s = queue_as(party(), *"AAB")
    assert order(s) == "ABA"
    s = run(s, RemoveEntry(B, s.queue[1].id))
    assert order(s) == "AA", "with only one singer left there is nobody to take turns with"


def test_a_song_still_preparing_does_not_leave_its_singer_back_to_back() -> None:
    """K1 is still preparing, so B's ready song plays first. K1 keeps the front, and K's second song does not
    follow it straight away: the rotation is rebuilt as B's song leaves the queue."""
    s = queue_as(party(), *"ABA")
    b = s.queue[1]
    s = run(s, QueueSong(C, song("c")))
    assert order(s) == "ABCA"
    s = run(s, SongReady(b.song.id))
    assert playing(s).origin == FromQueue(b)
    assert order(s) == "ACA"


def test_a_singers_ready_second_song_takes_their_turn_and_the_first_waits_a_round() -> None:
    """Found by the 5-phone party: K's first song is preparing, K's second is ready. K sings the ready one,
    and the one still preparing goes behind everyone else, never straight after K."""
    k1, b1, k2 = song("k1"), song("b1"), song("k2")
    s = run(party(), QueueSong(A, k1), QueueSong(B, b1), QueueSong(A, k2))
    assert order(s) == "ABA"
    s = run(s, SongReady(k2.id))
    assert playing(s).song == k2
    assert order(s) == "BA", "A just sang, so A's song still preparing waits behind B"


def test_a_turn_belongs_to_the_singer_not_to_one_song() -> None:
    """User, 2026-11-15: a singer whose song is still preparing goes first next. If one of their later songs is
    ready, that one takes their turn, rather than someone else singing again."""
    d1, m1, j1, m2 = song("d1"), song("m1"), song("j1"), song("m2")
    s = run(party(), SongReady(d1.id), QueueSong(D, d1))
    s = run(s, QueueSong(A, m1), QueueSong(B, j1), QueueSong(A, m2), SongReady(j1.id), SongReady(m2.id))
    assert order(s) == "ABA"
    s = run(s, TrackEnded(playing(s).play_id))
    assert playing(s).song == m2, "A is first in line and has a ready song, so B does not jump ahead"
    assert order(s) == "BA"


def test_a_singer_with_nothing_ready_stays_first_in_line() -> None:
    a1, b1, c1, a2 = song("a1"), song("b1"), song("c1"), song("a2")
    s = run(party(), QueueSong(A, a1), QueueSong(B, b1), QueueSong(C, c1))
    s = run(s, SongReady(b1.id), SongReady(c1.id))
    assert playing(s).song == b1 and order(s) == "AC"
    s = run(s, TrackEnded(playing(s).play_id))
    assert playing(s).song == c1 and order(s) == "A"
    s = run(s, QueueSong(B, song("b2")), SongReady(a1.id), TrackEnded(playing(s).play_id))
    assert playing(s).song == a1, "A waited two turns for their download and sings as soon as it is ready"


def test_random_nights_everyone_sings_equally() -> None:
    """Five phones, one queueing 2 at a time all night, songs taking random time to prepare. Whenever X starts a
    song: X did not sing the song before it while anyone else had a song queued, and nobody else had a ready
    song waiting, unsung, since X's previous song started."""
    singers = [SingerId(x) for x in "JKBOM"]
    for seed in range(40):
        rnd = random.Random(seed)
        s = run(initial_state(None), *(Hello(x, x) for x in singers), TvPresence(True))
        preparing: dict[SongId, int] = {}
        ready_since: dict[EntryId, int] = {}
        last_start: dict[SingerId, int] = {}
        last_play = None
        previous: SingerId | None = None

        def step(state: PartyState, inp: Input) -> PartyState:
            nonlocal previous
            after = run(state, inp)
            if isinstance(after.now, Playing) and isinstance(after.now.origin, FromQueue) and after.now != state.now:
                x = after.now.origin.entry.singer
                assert x != previous or all(e.singer == x for e in after.queue), (seed, "twice in a row", x)
                previous = x
            return after

        for t in range(300):
            for sid in list(preparing):
                preparing[sid] -= 1
                if preparing[sid] <= 0:
                    del preparing[sid]
                    s = step(s, SongReady(sid))
            r = rnd.random()
            if r < 0.45:
                who = singers[0] if r < 0.25 else rnd.choice(singers[1:])
                for _ in range(2 if who == singers[0] else 1):
                    m = song(f"{seed}-{s.next_entry_id}")
                    s = step(s, QueueSong(who, m))
                    preparing[m.id] = rnd.choice((0, 1, 3, 8))
            elif r < 0.75 and isinstance(s.now, Playing):
                s = step(s, TrackEnded(s.now.play_id))
            ready_since.update({e.id: t for e in s.queue if e.song.id in s.ready and e.id not in ready_since})
            if isinstance(s.now, Playing) and isinstance(s.now.origin, FromQueue) and s.now.play_id != last_play:
                last_play, x = s.now.play_id, s.now.origin.entry.singer
                if x in last_start:
                    skipped = [y.singer for y in s.queue if y.singer != x and ready_since.get(y.id, t) < last_start[x]
                               and last_start.get(y.singer, -1) < last_start[x]]
                    assert not skipped, (seed, t, x, skipped)
                last_start[x] = t


def test_the_last_singer_waits_rather_than_sing_twice_in_a_row() -> None:
    """User, 2026-11-15, example 10: "just wait, keep it simple". J1 ends; only J2 is ready; K1 and B1 are still
    preparing. A filler plays until K1 is ready, then K, then J2 (B1 still preparing), then Beauty."""
    j1, k1, b1, j2 = song("j1"), song("k1"), song("b1"), song("j2")
    s = run(party(), SongReady(j1.id), QueueSong(A, j1), QueueSong(B, k1), QueueSong(C, b1),
            SongReady(j2.id), QueueSong(A, j2))
    s = run(s, TrackEnded(playing(s).play_id))
    assert isinstance(s.now, Idle) and order(s) == "BCA"
    req = filler_request(s)
    assert req is not None, "the TV plays a filler while it waits"
    s = run(s, FillerPicked(req.token, song("f")), SongReady(k1.id))
    assert playing(s).origin == Filler(), "a ready song never cuts a filler short"
    s = run(s, TrackEnded(playing(s).play_id))
    assert playing(s).song == k1
    s = run(s, TrackEnded(playing(s).play_id))
    assert playing(s).song == j2, "J did not sing last, so J2 may go ahead of B1, which is still preparing"
    s = run(s, SongReady(b1.id), TrackEnded(playing(s).play_id))
    assert playing(s).song == b1


def test_while_the_tv_waits_the_queue_shows_the_last_singer_last() -> None:
    """Found in review: J1 ends and the TV waits for K1. Beauty adds a song. The phones must show it before J2,
    because Beauty really does sing before Jacky."""
    j1, k1, j2, b1 = song("j1"), song("k1"), song("j2"), song("b1")
    s = run(party(), SongReady(j1.id), QueueSong(A, j1), QueueSong(B, k1), SongReady(j2.id), QueueSong(A, j2))
    s = run(s, TrackEnded(playing(s).play_id))
    assert isinstance(s.now, Idle) and order(s) == "BA"
    s = run(s, QueueSong(C, b1))
    assert order(s) == "BCA"
    s = run(s, SongReady(b1.id))
    assert playing(s).song == b1 and order(s) == "BA"


def test_a_singer_alone_in_the_queue_keeps_singing() -> None:
    s = run(party(), SongReady(song("1").id), SongReady(song("2").id), QueueSong(A, song("1")), QueueSong(A, song("2")))
    s = run(s, TrackEnded(playing(s).play_id))
    assert playing(s).song == song("2"), "nobody else is waiting, so there is no one to wait for"


def test_move_to_front_survives_the_next_song() -> None:
    """v1: a song moved to the front leads the rotation, so the next add keeps it first."""
    s = queue_as(party(), *"ABB")
    last_b = s.queue[-1].id
    s = run(s, MoveEntry(C, last_b, Front()))
    assert order(s) == "BAB"
    s = queue_as(s, "C")
    assert order(s) == "BACB"
    assert s.queue[0].id == last_b


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
    assert s.settings == Settings(vocal_level=0.4, vocal_restore=0.4, av_offset_s=0.2)
    assert reduce(party(), Skip(A, PlayId(1))).outcome == Rejected("nothing_playing")


def test_seek_restarts_or_jumps_without_touching_the_queue() -> None:
    """Spec "Move around in the song": restart, +5 s, and the progress bar keep the song, queue, key, and count."""
    s = run(party(), SongReady(song("0").id), QueueSong(A, song("0")), QueueSong(B, song("q")))
    p = playing(s).play_id
    s = run(s, SetKey(A, p, 2), SetPaused(A, p, True))
    before = s
    s = run(s, Seek(B, p, 42.5), Seek(C, p, 0.0), Seek(C, p, 0.0))
    assert playing(s).seek == SeekTo(3, 0.0), "each seek is new, even to the same place"
    assert playing(s).play_id == p and playing(s).semitones == 2 and playing(s).paused
    assert s.queue == before.queue and s.next_play_id == before.next_play_id
    assert playing(run(s, Seek(A, p, 999.0))).seek == SeekTo(4, 199.0), "past the end lands 1 s before it"
    assert playing(run(s, Seek(A, p, -3.0))).seek == SeekTo(4, 0.0)
    assert reduce(s, Seek(A, p, float("nan"))).outcome == Rejected("invalid_value")
    assert reduce(s, Seek(A, PlayId(p + 1), 1.0)).outcome == Rejected("stale_play")
    assert reduce(party(), Seek(A, PlayId(1), 1.0)).outcome == Rejected("nothing_playing")
    s = run(s, TrackEnded(p))
    assert reduce(s, Seek(A, p, 1.0)).outcome == Rejected("nothing_playing"), "a late seek cannot move the next song"


def test_advanced_lyrics_is_on_by_default() -> None:
    assert initial_state(None).settings.advanced_lyrics


def test_key_resets_and_vocal_level_persists_across_songs() -> None:
    s = run(party(), SongReady(song("0").id), SongReady(song("1").id), QueueSong(A, song("0")), QueueSong(B, song("1")))
    p = playing(s).play_id
    s = run(s, SetKey(A, p, -2), SetVocal(A, 0.7), TrackEnded(p))
    assert playing(s).semitones == 0 and s.settings.vocal_level == 0.7


def test_key_steps_apply_to_the_current_key_so_a_lagging_phone_cannot_move_it_back() -> None:
    """Spec "Keep settings in sync": phone A raised the key to +2; phone B still shows 0 and presses +.
    With absolute setters B would send +1 and pull the key down. A step lands on +3."""
    s = run(party(), SongReady(song("0").id), QueueSong(A, song("0")))
    p = playing(s).play_id
    s = run(s, StepKey(A, p, 1), StepKey(A, p, 1), StepKey(B, p, 1))
    assert playing(s).semitones == 3
    s = run(s, StepKey(B, p, -1), SetKey(C, p, 0))
    assert playing(s).semitones == 0, "Reset is still absolute"
    s = run(s, *(StepKey(A, p, 1) for _ in range(9)))
    assert playing(s).semitones == 6, "steps clamp at the top of the range"
    assert reduce(s, StepKey(A, p, 1)).state is s
    assert reduce(s, StepKey(A, p, 2)).outcome == Rejected("invalid_value")
    assert reduce(s, StepKey(A, PlayId(p + 1), 1)).outcome == Rejected("stale_play")


def test_vocal_switch_restores_the_same_level_for_every_phone() -> None:
    """Spec "Keep settings in sync": the restore level lives on the server, so the switch on any phone
    turns the vocal back on at the level it had, and at full if it was never on."""
    s = party()
    s = run(s, SetVocalOn(A, True))
    assert s.settings.vocal_level == 1.0, "never on: turns on at full"
    s = run(s, SetVocal(A, 0.35), SetVocalOn(B, False))
    assert s.settings.vocal_level == 0.0
    s = run(s, SetVocalOn(C, True))
    assert s.settings.vocal_level == 0.35, "phone C restores the level phone A set"
    s = run(s, SetVocal(A, 0.0), SetVocalOn(B, True))
    assert s.settings.vocal_level == 0.35, "dragging the slider to zero does not lose the restore level"


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


def test_restart_keep_keeps_order_until_the_next_song() -> None:
    """Saved A B B; keep -> same order; a new C song rebuilds the rotation: A B C B."""
    s = initial_state(saved("A", "B", "B"))
    assert isinstance(s.phase, AwaitingRestartChoice) and s.queue == ()
    assert s.settings == Settings(vocal_level=0.3, av_offset_s=0.1)
    s = run(s, Hello(C, "Cat"))
    assert reduce(s, QueueSong(C, song("c"))).outcome == Rejected("awaiting_restart_choice")
    s = run(s, ResolveRestart(keep=True))
    assert order(s) == "ABB"
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


def test_durable_snapshot_is_queue_and_settings_only() -> None:
    assert {f.name for f in dataclasses.fields(DurableSnapshot)} == {"queue", "settings"}
    s = run(party(), SongReady(song("0").id), QueueSong(A, song("0")))
    s = queue_as(s, "B")
    snap = durable(s)
    assert [e.singer for e in snap.queue] == [A, B], "the now-playing queued song is saved at the front"
    restarted = run(initial_state(snap), ResolveRestart(keep=True))


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
    st.builds(StepKey, singers, play_ids, st.sampled_from([-1, 1, 2])),
    st.builds(SetVocal, singers, st.floats(-0.5, 1.5)),
    st.builds(SetVocalOn, singers, st.booleans()),
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
    if isinstance(s.phase, AwaitingRestartChoice):
        assert s.queue == () and isinstance(s.now, Idle)
    if isinstance(s.phase, Running) and isinstance(s.now, Idle):
        assert not any(e.song.id in s.ready and e.singer != s.last_singer for e in s.queue), \
            "an idle TV only waits when the one ready song is the last singer's"
    if isinstance(s.now, Playing):
        assert s.now.play_id < s.next_play_id


def no_avoidable_back_to_back(s: PartyState) -> bool:
    """A singer appears twice in a row only when nobody else has a song after them."""
    singing = s.now.origin.entry.singer if isinstance(s.now, Playing) and isinstance(s.now.origin, FromQueue) else None
    q = [singing, *(e.singer for e in s.queue)] if singing else [e.singer for e in s.queue]
    return all(q[i] != q[i + 1] or all(x == q[i] for x in q[i + 2:]) for i in range(len(q) - 1))


@settings(max_examples=300, deadline=None)
@given(starts, st.lists(inputs, max_size=40))
def test_any_input_sequence_keeps_invariants(start: DurableSnapshot | None, seq: list[Input]) -> None:
    """Entry ids unique; now-playing entry not in queue; rejected inputs leave state identical; whenever a song
    joins or leaves the queue (outside a restart) the queue is a rotation with no avoidable back-to-back singer;
    a double skip skips one song."""
    s = initial_state(start)
    check_invariants(s)
    for inp in seq:
        step = reduce(s, inp)
        if isinstance(step.outcome, Rejected):
            assert step.state is s
        changed = {e.id for e in s.queue} != {e.id for e in step.state.queue}
        if changed and not isinstance(inp, ResolveRestart):
            assert no_avoidable_back_to_back(step.state), (inp, [e.singer for e in step.state.queue])
        s = step.state
        check_invariants(s)
        if isinstance(s.now, Playing):
            once = reduce(s, Skip(A, s.now.play_id)).state
            twice = reduce(once, Skip(B, s.now.play_id))
            assert isinstance(twice.outcome, Rejected) and twice.state is once
