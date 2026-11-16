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
from dataclasses import dataclass
from typing import NewType

from karaoke.core import SingerId, SongId, SongMeta
from karaoke.vocab import RejectReason

EntryId = NewType("EntryId", int)
PlayId = NewType("PlayId", int)
"""Increments every time a song starts on the TV. Commands that target 'the
current song' carry it, so a stale skip from a second phone cannot skip the
next song too (idempotent skip)."""

KEY_MIN, KEY_MAX = -6, 6
AV_OFFSET_MAX_S = 1.0
NAME_MAX = 32
FILLER_MEMORY = 20
SEEK_END_GAP_S = 1.0
"""A seek past the end lands this far before it, so the song still ends normally."""


@dataclass(frozen=True, slots=True)
class QueueEntry:
    id: EntryId
    song: SongMeta
    singer: SingerId
    singer_name: str
    """The name the singer had when they queued this song. A later rename does not change it, so a 咪霸 who
    renames between songs shows each song under the name used, while fairness counts by `singer` (the phone)."""


# ---- what the TV should be doing -------------------------------------------------------

@dataclass(frozen=True, slots=True)
class FromQueue:
    entry: QueueEntry


@dataclass(frozen=True, slots=True)
class Filler:
    """Not a queue entry. Has no singer, so it never takes a turn in the rotation."""


@dataclass(frozen=True, slots=True)
class SeekTo:
    """The latest jump within the playing song (restart, +5 s, the progress bar). A target, not a step."""

    seq: int
    """Increases with every seek in this play, so seeking twice to the same place jumps twice."""
    to_s: float


@dataclass(frozen=True, slots=True)
class Playing:
    play_id: PlayId
    song: SongMeta
    origin: FromQueue | Filler
    paused: bool = False
    semitones: int = 0
    """Per play. Resets to 0 for the next song."""
    seek: SeekTo | None = None
    """None until someone seeks. The TV applies each new seq once. Never touches the queue or fairness."""


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
    vocal_restore: float = 1.0
    """The level the vocal switch turns back on to: the last level above zero. Held here, not on the phones,
    so every phone restores the same level."""
    av_offset_s: float = 0.0
    """TV display lag. Video and lyrics are drawn this much earlier than the audible position."""
    advanced_lyrics: bool = True
    """The advanced lyrics matching switch. Every song has both lyrics; this picks which the TV draws."""


@dataclass(frozen=True, slots=True)
class PartyState:
    phase: Phase
    queue: tuple[QueueEntry, ...]
    now: Now
    last_singer: SingerId | None
    """Whose queued song started most recently. Fillers do not change it. They may not sing again next while
    someone else has a song queued (the TV waits instead, see fairness.next_up). Not saved: a restart clears it."""
    singers: Mapping[SingerId, str]
    """Latest display name per singer, from Hello/Rename. A singer is a phone (its Wi-Fi address), not a name.
    Queue entries carry their own name; this map is the fallback and the record of who has said hello."""
    ready: frozenset[SongId]
    """Songs known to be fully in the library. Fed only by SongReady facts from the Preparer.
    The reducer never guesses readiness; one path for library songs and freshly prepared ones."""
    settings: Settings
    tv_connected: bool
    recent_fillers: tuple[SongId, ...]
    """Last FILLER_MEMORY fillers, newest first, so random picks don't repeat."""
    next_entry_id: EntryId
    next_play_id: PlayId


@dataclass(frozen=True, slots=True)
class DurableSnapshot:
    """The only thing written to disk. Derived by `projections.durable(state)`.

    Turn order is not stored: it is rebuilt from the queue itself (fairness.rotated).
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
