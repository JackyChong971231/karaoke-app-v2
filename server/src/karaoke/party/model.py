"""Party state: everything the party decides, nothing the world reports continuously.

Owned by exactly one function, `reduce`. All types are frozen, the shell holds the only
reference, and `reduce` is the only function in the codebase that returns a new PartyState
(a 10-line AST test, tests/test_boundaries.py, fails if any module outside karaoke.party
calls `replace(` on a party type or constructs PartyState).

What is deliberately NOT here:
- Preparation progress (owned by `songs.prepare.Preparer`, merged into views at the read boundary).
- Playback position (owned by the TV's audio clock, relayed by `shell.hub`, merged into views).
- Library contents (owned by `songs.library.Library`; the party only learns `SongReady` facts).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import NewType

from karaoke.core import SingerId, SongId, SongMeta
from karaoke.vocab import RejectReason

EntryId = NewType("EntryId", int)
PlayId = NewType("PlayId", int)
"""Increments every time a song starts on the TV. Commands that target 'the
current song' carry it, so a stale skip from a second phone cannot skip the
next song too (idempotent skip)."""

KEY_MIN, KEY_MAX = -6, 6


@dataclass(frozen=True, slots=True)
class QueueEntry:
    id: EntryId
    song: SongMeta
    singer: SingerId
    round: int
    """Fixed when the entry is added: sung tonight + already queued + 1. Never recomputed,
    except once when a kept queue is renumbered at restart (see fairness.renumber_kept)."""


@dataclass(frozen=True, slots=True)
class Fairness:
    """Resets on every start. DurableSnapshot has no field for it, so a restart cannot restore it."""

    join_order: tuple[SingerId, ...] = ()
    """A singer joins tonight with their first queued song (Assumption, see rationale open questions)."""
    sung: Mapping[SingerId, int] = field(default_factory=dict)
    """Songs started tonight per singer. Counted when a song STARTS, not when it ends,
    so a singer's new song queued during their own song gets the right round."""


# ---- what the TV should be doing -------------------------------------------------------

@dataclass(frozen=True, slots=True)
class FromQueue:
    entry: QueueEntry


@dataclass(frozen=True, slots=True)
class Filler:
    """Not a queue entry. Has no singer. Never touches Fairness."""


@dataclass(frozen=True, slots=True)
class Playing:
    play_id: PlayId
    song: SongMeta
    origin: FromQueue | Filler
    paused: bool = False
    semitones: int = 0
    """Per play. Resets to 0 for the next song."""


@dataclass(frozen=True, slots=True)
class Idle:
    """Nothing on the TV. `projections.filler_request` asks the shell for a filler while
    Idle and nothing in the queue is ready."""


Now = Playing | Idle


# ---- restart ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class SavedEntry:
    song: SongMeta
    singer: SingerId
    singer_name: str


@dataclass(frozen=True, slots=True)
class AwaitingRestartChoice:
    """Boot found a non-empty saved queue. The prompt shows on the TV and every phone.
    The first ResolveRestart wins; later ones are rejected as `already_resolved`.
    Queue edits and filler wait until the answer."""

    offer: tuple[SavedEntry, ...]


@dataclass(frozen=True, slots=True)
class Running:
    pass


Phase = AwaitingRestartChoice | Running


@dataclass(frozen=True, slots=True)
class Settings:
    vocal_level: float = 0.0
    """0.0 (off) .. 1.0 (full). Party-wide and sticky across songs (Assumption)."""
    av_offset_s: float = 0.0
    """TV display lag. Video and lyrics are drawn this much earlier than the audible position."""


@dataclass(frozen=True, slots=True)
class PartyState:
    phase: Phase
    queue: tuple[QueueEntry, ...]
    now: Now
    fairness: Fairness
    singers: Mapping[SingerId, str]
    """Display names, from Hello/Rename. Names live on the phone; this is the latest one seen."""
    ready: frozenset[SongId]
    """Songs known to be fully in the library. Fed only by SongReady facts from the Preparer.
    The reducer never guesses readiness; one path for library songs and freshly prepared ones."""
    settings: Settings
    tv_connected: bool
    recent_fillers: tuple[SongId, ...]
    """Last N fillers, so random picks don't repeat back to back."""
    next_entry_id: EntryId
    next_play_id: PlayId


@dataclass(frozen=True, slots=True)
class DurableSnapshot:
    """The only thing written to disk. Derived by `projections.durable(state)`.

    No fairness fields on purpose: the spec resets counts and join order on restart,
    and a type without the fields cannot accidentally restore them.
    """

    queue: tuple[SavedEntry, ...]
    """The live queue, or the still-unanswered restart offer, so a crash during the prompt loses nothing.
    The now-playing queued song is saved at the front: it had not finished."""
    settings: Settings


# ---- reply to the sender ---------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Accepted:
    pass


@dataclass(frozen=True, slots=True)
class Rejected:
    reason: RejectReason


Outcome = Accepted | Rejected


@dataclass(frozen=True, slots=True)
class Step:
    """Result of one reduction. The only 'effect' left is the reply to whoever sent the input.

    Persist, broadcast, preparation, and filler picking are NOT effects. They are projections of
    `state` that the shell reconciles after every step (see projections.py and rationale).
    """

    state: PartyState
    outcome: Outcome
