"""Everything the outside world needs from party state, as pure functions of it.

This is where the assigned 'effects' went. The shell calls each projection after every step and
reconciles the world toward it. A projection cannot be forgotten by a new reducer branch, and it
recomputes correctly after a crash, where an emitted-then-lost effect would not.

Views for the wire live in karaoke.shell.views, because they merge in state the party does not own
(preparation progress, playback position). These three projections are the party's own.
"""

from __future__ import annotations

from dataclasses import dataclass

from karaoke.core import SongId, SongMeta
from karaoke.party.model import DurableSnapshot, PartyState, PlayId


def durable(state: PartyState) -> DurableSnapshot:
    """What survives a restart. The shell writes it when it differs from the last write.

    queue = the restart offer while AwaitingRestartChoice, else
            [now-playing queued entry, if any] + live queue, as SavedEntry with singer names.
    Fillers are never saved. Fairness is never saved (the type has no field for it).
    """
    raise NotImplementedError


def preparation_demand(state: PartyState) -> tuple[SongMeta, ...]:
    """Songs the party wants in the library, most urgent first. Deduplicated by song id.

    = queue songs in queue order. (Now-playing is ready by definition.)
    The Preparer receives the WHOLE list every time (declarative, idempotent). It starts what is
    missing, reports SongReady for what is already on disk, and re-prioritizes when the order changes,
    so a 'play next' move also moves that song's preparation forward.
    Restart recovery is this same call: the first demand after boot covers every kept song.
    """
    raise NotImplementedError


@dataclass(frozen=True, slots=True)
class FillerRequest:
    token: PlayId
    """= state.next_play_id. Changes whenever any song starts, which invalidates stale picks."""
    avoid: frozenset[SongId]
    """recent_fillers plus every queued song, so a filler never pre-empts someone's pick."""


def filler_request(state: PartyState) -> FillerRequest | None:
    """Non-None iff phase is Running, now is Idle, and no queue entry is ready.

    The shell answers with FillerPicked(token, song) from Library.random_pick(avoid).
    With an empty library it answers nothing and the TV shows its idle screen with the QR code.
    """
    raise NotImplementedError
