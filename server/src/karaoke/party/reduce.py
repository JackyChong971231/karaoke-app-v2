"""The single writer of party state. Pure: no I/O, no clock, no randomness, no imports
outside karaoke.core and karaoke.party (import-linter contract `party-is-pure`).

Reading this file and fairness.py is enough to know every rule of the party.
"""

from __future__ import annotations

from typing import assert_never

from karaoke.party import fairness
from karaoke.party.inputs import (
    FillerPicked, Hello, Input, MoveEntry, QueueSong, RemoveEntry, Rename, ResolveRestart,
    SetAvOffset, SetKey, SetPaused, SetVocal, Skip, SongReady, TrackEnded, TrackFailed, TvPresence,
)
from karaoke.party.model import (
    AwaitingRestartChoice, DurableSnapshot, Idle, PartyState, Playing, Rejected, Step,
)


def initial_state(saved: DurableSnapshot | None) -> PartyState:
    """State at boot. Fairness is always fresh.

    saved is None or has an empty queue -> phase Running, empty queue, saved settings.
    saved has queue entries            -> phase AwaitingRestartChoice(offer=saved.queue), empty live queue.
    `ready` starts empty: the Preparer reports SongReady for library songs as soon as they are demanded.
    """
    raise NotImplementedError


def reduce(state: PartyState, inp: Input) -> Step:
    """Apply one input. Never raises for bad or stale input: returns Rejected(reason) and the
    unchanged state. Raises only on broken invariants (a bug).

    TODO pseudocode, by input:

    Hello(by, name) / Rename(by, name):
        singers[by] = name (trimmed, 1..32 chars else invalid_value)

    ResolveRestart(keep):
        phase is Running -> Rejected("already_resolved")            # first answer wins
        keep  -> queue, fairness = fairness.renumber_kept(offer, next_entry_id)
                 singers |= {e.singer: e.singer_name for e in offer} (existing live names win)
        !keep -> queue = ()
        phase = Running; then _settle(state)

    Any queue-editing command while AwaitingRestartChoice -> Rejected("awaiting_restart_choice")

    QueueSong(by, song):
        by not in singers -> Rejected("unknown_singer")             # phone must Hello first
        f   = fairness.with_joined(state.fairness, by)
        e   = QueueEntry(next_entry_id, song, by, fairness.next_round(f, queue, by))
        queue = fairness.insert_fairly(queue, e, f.join_order); next_entry_id += 1
        _settle(state)                                               # starts it at once if Idle and ready

    RemoveEntry(entry) / MoveEntry(entry, to):
        entry not in queue -> Rejected("unknown_entry")              # e.g. another phone removed it first
        MoveEntry Before(x) with x not in queue -> Rejected("unknown_entry")
        Before(self) -> Accepted, no change

    SetPaused / Skip / SetKey (play id):
        now is Idle -> Rejected("nothing_playing")
        play != now.play_id -> Rejected("stale_play")                # second phone's skip is a no-op
        SetKey outside KEY_MIN..KEY_MAX -> Rejected("invalid_value")
        Skip -> _advance(state)

    SetVocal(level) 0..1 / SetAvOffset(seconds) 0..1.0: update settings, else invalid_value.

    TrackEnded(play) / TrackFailed(play, _):
        play != now.play_id -> Rejected("stale_play")                # late report from a reloaded TV
        -> _advance(state)
        (TrackFailed advances too; the failure goes to the server log via the shell, not to state.)

    SongReady(song):  ready |= {song}; _settle(state)

    FillerPicked(token, song):
        token != next_play_id or now is not Idle or phase is not Running -> Accepted, no change
        (stale picks are normal, not errors: a queued song became ready meanwhile)
        -> _start(state, song, Filler()); recent_fillers = (song.id, *recent)[:10]

    TvPresence(connected): tv_connected = connected
    """
    match inp:
        case Hello() | Rename() | QueueSong() | RemoveEntry() | MoveEntry() | SetPaused() | Skip() \
                | SetKey() | SetVocal() | SetAvOffset() | ResolveRestart() | TrackEnded() | TrackFailed() \
                | SongReady() | FillerPicked() | TvPresence():
            raise NotImplementedError
        case _:
            assert_never(inp)


def _advance(state: PartyState) -> PartyState:
    """Current song is over (ended, failed, or skipped). Go Idle, then settle.

    The finished song is not re-queued; its singer's count was already taken at start.
    """
    raise NotImplementedError


def _settle(state: PartyState) -> PartyState:
    """If the TV is Idle, start the first READY entry in queue order.

    TODO pseudocode:
        if phase is not Running or now is not Idle: return state
        for e in queue:                         # in order
            if e.song.id in ready:
                return _start(state without e, e.song, FromQueue(e))
        return state                            # stays Idle; projections.filler_request takes over

    Spec rules encoded here:
    - "If a song is not ready when its turn comes, the next ready song plays. The unready song keeps
      its place at the front": unready entries are skipped over, never moved.
    - A filler that is Playing is not Idle, so a queued song becoming ready does NOT interrupt it
      (product assumption: the filler plays to its end; any singer can Skip it).
    """
    raise NotImplementedError


def _start(state: PartyState, song, origin) -> PartyState:
    """now = Playing(next_play_id, song, origin, paused=False, semitones=0); next_play_id += 1.
    FromQueue: fairness.sung[singer] += 1 here, at start."""
    raise NotImplementedError


def _reject(state: PartyState, reason) -> Step:
    return Step(state, Rejected(reason))
