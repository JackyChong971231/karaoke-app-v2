"""The single writer of party state. Pure: no I/O, no clock, no randomness, no imports
outside karaoke.core and karaoke.party (import-linter contract `party-is-pure`).

Reading this file and fairness.py is enough to know every rule of the party.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import assert_never

from karaoke.core import SongMeta
from karaoke.party import fairness
from karaoke.party.inputs import (
    Before, End, FillerPicked, Front, Hello, Input, MoveEntry, QueueSong, RemoveEntry, Rename, ResolveRestart, Seek,
    SetAdvancedLyrics, SetAvOffset, SetKey, SetPaused, SetVocal, SetVocalOn, Skip, SongReady, StepKey, TrackEnded, TrackFailed,
    TvPresence,
)
from karaoke.party.model import (
    AV_OFFSET_MAX_S, FILLER_MEMORY, KEY_MAX, KEY_MIN, NAME_MAX, SEEK_END_GAP_S, Accepted, AwaitingRestartChoice, DurableSnapshot,
    EntryId, Fairness, Filler, FromQueue, Idle, PartyState, PlayId, Playing, QueueEntry, Rejected, Running, SeekTo,
    Settings, Step,
)
from karaoke.vocab import RejectReason


def initial_state(saved: DurableSnapshot | None) -> PartyState:
    """State at boot. Fairness is always fresh.

    A saved non-empty queue becomes a keep-or-new offer; the live queue starts empty.
    `ready` starts empty: the Preparer reports SongReady for library songs as soon as they are demanded.
    """
    offer = saved.queue if saved else ()
    return PartyState(
        phase=AwaitingRestartChoice(offer) if offer else Running(),
        queue=(),
        now=Idle(),
        fairness=Fairness(),
        singers={},
        ready=frozenset(),
        settings=saved.settings if saved else Settings(),
        tv_connected=False,
        recent_fillers=(),
        next_entry_id=EntryId(1),
        next_play_id=PlayId(1),
    )


def reduce(state: PartyState, inp: Input) -> Step:
    """Apply one input. Never raises for bad or stale input: returns Rejected(reason) and the
    unchanged state object. Raises only on broken invariants (a bug)."""
    match inp:
        case Hello(by, name) | Rename(by, name):
            clean = name.strip()
            if not 1 <= len(clean) <= NAME_MAX:
                return _reject(state, "invalid_value")
            if state.singers.get(by) == clean:
                return Step(state, Accepted())
            return _ok(replace(state, singers={**state.singers, by: clean}))

        case ResolveRestart(keep):
            if not isinstance(state.phase, AwaitingRestartChoice):
                return _reject(state, "already_resolved")
            return _ok(_settle(_resolve_restart(state, state.phase, keep)))

        case QueueSong() | RemoveEntry() | MoveEntry() if isinstance(state.phase, AwaitingRestartChoice):
            return _reject(state, "awaiting_restart_choice")

        case QueueSong(by, song, name):
            if by not in state.singers:
                return _reject(state, "unknown_singer")
            shown = (name or "").strip()[:NAME_MAX] or state.singers[by]
            joined = fairness.with_joined(state.fairness, by)
            entry = QueueEntry(state.next_entry_id, song, by, fairness.next_round(joined, state.queue, by), shown)
            return _ok(_settle(replace(
                state,
                queue=fairness.insert_fairly(state.queue, entry, joined.join_order),
                fairness=joined,
                next_entry_id=EntryId(state.next_entry_id + 1),
            )))

        case RemoveEntry(_, entry_id):
            if _find(state, entry_id) is None:
                return _reject(state, "unknown_entry")
            return _ok(_settle(replace(state, queue=tuple(e for e in state.queue if e.id != entry_id))))

        case MoveEntry(_, entry_id, to):
            moving = _find(state, entry_id)
            if moving is None or (isinstance(to, Before) and _find(state, to.entry) is None):
                return _reject(state, "unknown_entry")
            if isinstance(to, Before) and to.entry == entry_id:
                return Step(state, Accepted())
            return _ok(replace(state, queue=_moved(state.queue, moving, to)))

        case SetPaused(_, play, paused):
            if (bad := _check_play(state, play)) is not None:
                return _reject(state, bad)
            assert isinstance(state.now, Playing)
            return _ok(replace(state, now=replace(state.now, paused=paused)))

        case SetKey(_, play, semitones):
            if (bad := _check_play(state, play)) is not None:
                return _reject(state, bad)
            if not KEY_MIN <= semitones <= KEY_MAX:
                return _reject(state, "invalid_value")
            assert isinstance(state.now, Playing)
            return _ok(replace(state, now=replace(state.now, semitones=semitones)))

        case StepKey(_, play, step):
            if (bad := _check_play(state, play)) is not None:
                return _reject(state, bad)
            if step not in (-1, 1):
                return _reject(state, "invalid_value")
            assert isinstance(state.now, Playing)
            moved = min(KEY_MAX, max(KEY_MIN, state.now.semitones + step))
            if moved == state.now.semitones:
                return Step(state, Accepted())
            return _ok(replace(state, now=replace(state.now, semitones=moved)))

        case Seek(_, play, to_s):
            if (bad := _check_play(state, play)) is not None:
                return _reject(state, bad)
            if not math.isfinite(to_s):
                return _reject(state, "invalid_value")
            assert isinstance(state.now, Playing)
            last = max(0.0, state.now.song.duration_s - SEEK_END_GAP_S)
            seek = SeekTo((state.now.seek.seq if state.now.seek else 0) + 1, min(last, max(0.0, to_s)))
            return _ok(replace(state, now=replace(state.now, seek=seek)))

        case Skip(_, play) | TrackEnded(play) | TrackFailed(play, _):
            if (bad := _check_play(state, play)) is not None:
                return _reject(state, bad)
            return _ok(_settle(replace(state, now=Idle())))

        case SetVocal(_, level):
            if not 0.0 <= level <= 1.0:
                return _reject(state, "invalid_value")
            restore = level if level > 0 else state.settings.vocal_restore
            return _ok(replace(state, settings=replace(state.settings, vocal_level=level, vocal_restore=restore)))

        case SetVocalOn(_, on):
            level = state.settings.vocal_restore if on else 0.0
            return _ok(replace(state, settings=replace(state.settings, vocal_level=level)))

        case SetAvOffset(_, seconds):
            if not 0.0 <= seconds <= AV_OFFSET_MAX_S:
                return _reject(state, "invalid_value")
            return _ok(replace(state, settings=replace(state.settings, av_offset_s=seconds)))

        case SetAdvancedLyrics(_, on):
            return _ok(replace(state, settings=replace(state.settings, advanced_lyrics=on)))

        case SongReady(song):
            if song in state.ready:
                return Step(state, Accepted())
            return _ok(_settle(replace(state, ready=state.ready | {song})))

        case FillerPicked(token, song):
            # A stale pick is normal (a queued song became ready meanwhile), so it is accepted and dropped.
            if token != state.next_play_id or not isinstance(state.now, Idle) or not isinstance(state.phase, Running):
                return Step(state, Accepted())
            started = _start(state, song, Filler())
            return _ok(replace(started, recent_fillers=(song.id, *state.recent_fillers)[:FILLER_MEMORY]))

        case TvPresence(connected):
            if state.tv_connected == connected:
                return Step(state, Accepted())
            return _ok(replace(state, tv_connected=connected))

        case _:
            assert_never(inp)


def _resolve_restart(state: PartyState, prompt: AwaitingRestartChoice, keep: bool) -> PartyState:
    if not keep:
        return replace(state, phase=Running())
    queue, fresh = fairness.renumber_kept(prompt.offer, state.next_entry_id)
    kept_names = {e.singer: e.singer_name for e in prompt.offer}
    return replace(
        state,
        phase=Running(),
        queue=queue,
        fairness=fresh,
        singers={**kept_names, **state.singers},
        next_entry_id=EntryId(state.next_entry_id + len(queue)),
    )


def _settle(state: PartyState) -> PartyState:
    """If the TV is Idle, start the first READY entry in queue order.

    - "If a song is not ready when its turn comes, the next ready song plays. The unready song keeps
      its place at the front": unready entries are skipped over, never moved.
    - A filler that is Playing is not Idle, so a queued song becoming ready does NOT interrupt it.
    """
    if not isinstance(state.phase, Running) or not isinstance(state.now, Idle):
        return state
    for e in state.queue:
        if e.song.id in state.ready:
            rest = tuple(x for x in state.queue if x.id != e.id)
            return _start(replace(state, queue=rest), e.song, FromQueue(e))
    return state


def _start(state: PartyState, song: SongMeta, origin: FromQueue | Filler) -> PartyState:
    """A song counts as sung when it starts, so a song its singer queues during it gets the right round."""
    now = Playing(state.next_play_id, song, origin)
    f = state.fairness
    if isinstance(origin, FromQueue):
        singer = origin.entry.singer
        f = Fairness(join_order=f.join_order, sung={**f.sung, singer: f.sung.get(singer, 0) + 1})
    return replace(state, now=now, fairness=f, next_play_id=PlayId(state.next_play_id + 1))


def _moved(queue: tuple[QueueEntry, ...], moving: QueueEntry, to: Front | End | Before) -> tuple[QueueEntry, ...]:
    rest = tuple(e for e in queue if e.id != moving.id)
    match to:
        case Front():
            return (moving, *rest)
        case End():
            return (*rest, moving)
        case Before(target):
            i = next(i for i, e in enumerate(rest) if e.id == target)
            return (*rest[:i], moving, *rest[i:])
        case _:
            assert_never(to)


def _check_play(state: PartyState, play: PlayId) -> RejectReason | None:
    if not isinstance(state.now, Playing):
        return "nothing_playing"
    if play != state.now.play_id:
        return "stale_play"
    return None


def _find(state: PartyState, entry_id: EntryId) -> QueueEntry | None:
    return next((e for e in state.queue if e.id == entry_id), None)


def _ok(state: PartyState) -> Step:
    return Step(state, Accepted())


def _reject(state: PartyState, reason: RejectReason) -> Step:
    return Step(state, Rejected(reason))


