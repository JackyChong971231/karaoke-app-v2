"""Everything the outside world needs from party state, as pure functions of it.

The shell calls each projection after every step and reconciles the world toward it. A projection cannot
be forgotten by a new reducer branch, and it recomputes correctly after a crash, where an emitted-then-lost
effect would not.

Views for the wire live in karaoke.shell.views, because they merge in state the party does not own
(preparation progress, playback position). These three projections are the party's own.
"""

from __future__ import annotations

from dataclasses import dataclass

from karaoke.core import SongId, SongMeta
from karaoke.party.model import (
    AwaitingRestartChoice, DurableSnapshot, FromQueue, Idle, PartyState, Playing, PlayId, QueueEntry, Running,
    SavedEntry,
)


def durable(state: PartyState) -> DurableSnapshot:
    """What survives a restart: the unanswered offer, or the now-playing queued entry plus the live queue.
    Fillers are never saved. Fairness is never saved (the type has no field for it)."""
    if isinstance(state.phase, AwaitingRestartChoice):
        return DurableSnapshot(queue=state.phase.offer, settings=state.settings)
    entries: tuple[QueueEntry, ...] = state.queue
    if isinstance(state.now, Playing) and isinstance(state.now.origin, FromQueue):
        entries = (state.now.origin.entry, *entries)
    saved = tuple(SavedEntry(e.song, e.singer, e.singer_name) for e in entries)
    return DurableSnapshot(queue=saved, settings=state.settings)


def preparation_demand(state: PartyState) -> tuple[SongMeta, ...]:
    """Songs the party wants in the library, most urgent first: queue songs in queue order, deduplicated.

    The Preparer receives the whole list every time and reports SongReady for songs already on disk, so
    restart recovery is this same call, and a 'play next' move also moves that song's preparation forward.
    """
    seen: set[SongId] = set()
    out: list[SongMeta] = []
    for e in state.queue:
        if e.song.id not in seen:
            seen.add(e.song.id)
            out.append(e.song)
    return tuple(out)


@dataclass(frozen=True, slots=True)
class FillerRequest:
    token: PlayId
    """= state.next_play_id. Changes whenever any song starts, which invalidates stale picks."""
    avoid: frozenset[SongId]
    """recent_fillers plus every queued song, so a filler never pre-empts someone's pick."""
    recent: tuple[SongId, ...]
    """recent_fillers, newest first. When `avoid` covers the whole library, the pick falls back to the
    song played longest ago, so a small library rotates instead of repeating one song."""


def filler_request(state: PartyState) -> FillerRequest | None:
    """Non-None iff the TV is connected, phase is Running, now is Idle, and no queue entry is ready.

    The TV-connected condition keeps a filler from starting before the TV page opens; otherwise the first
    queued song of the night would wait behind a filler that nobody saw start.
    """
    if not (state.tv_connected and isinstance(state.phase, Running) and isinstance(state.now, Idle)):
        return None
    if any(e.song.id in state.ready for e in state.queue):
        return None
    avoid = frozenset(state.recent_fillers) | {e.song.id for e in state.queue}
    return FillerRequest(token=state.next_play_id, avoid=avoid, recent=state.recent_fillers)
