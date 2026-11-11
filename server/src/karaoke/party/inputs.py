"""Every way party state can change. One closed union; `reduce` matches it exhaustively
(`assert_never`), so a new input that the reducer forgets fails type checking.

Three origins, one type:
- Phone commands: carry `by`, the singer bound to the WebSocket at Hello. Parsed from wire in shell/parse.py.
- TV reports: what the audio engine observed (a track ended or could not load).
- Facts from the shell: the Preparer finished a song, the shell picked a filler, the TV (dis)connected.

All of them reference entities by ID (EntryId, PlayId, token), never by index, so
two phones editing at once both apply in arrival order with a well-defined result.
"""

from __future__ import annotations

from dataclasses import dataclass

from karaoke.core import SingerId, SongId, SongMeta
from karaoke.party.model import EntryId, PlayId

# ---- phone commands ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Hello:
    by: SingerId
    name: str


@dataclass(frozen=True, slots=True)
class Rename:
    by: SingerId
    name: str


@dataclass(frozen=True, slots=True)
class QueueSong:
    by: SingerId
    song: SongMeta
    """Already resolved at the boundary from a library ID or a catalog pick ID."""


@dataclass(frozen=True, slots=True)
class RemoveEntry:
    by: SingerId
    entry: EntryId


@dataclass(frozen=True, slots=True)
class Front:
    """'Play next'."""


@dataclass(frozen=True, slots=True)
class End:
    pass


@dataclass(frozen=True, slots=True)
class Before:
    entry: EntryId


Position = Front | End | Before


@dataclass(frozen=True, slots=True)
class MoveEntry:
    """The one way to reorder, including 'play next' (to=Front). A manual move is never
    undone by fairness; fairness only places NEW entries."""

    by: SingerId
    entry: EntryId
    to: Position


@dataclass(frozen=True, slots=True)
class SetPaused:
    by: SingerId
    play: PlayId
    paused: bool
    """Absolute, not a toggle: two phones tapping pause at once both mean 'paused'."""


@dataclass(frozen=True, slots=True)
class Skip:
    by: SingerId
    play: PlayId


@dataclass(frozen=True, slots=True)
class SetKey:
    by: SingerId
    play: PlayId
    semitones: int
    """Absolute. The phone sends current +/- 1; two concurrent taps from the same base land on one step."""


@dataclass(frozen=True, slots=True)
class SetVocal:
    by: SingerId
    level: float


@dataclass(frozen=True, slots=True)
class SetAvOffset:
    by: SingerId
    seconds: float


@dataclass(frozen=True, slots=True)
class ResolveRestart:
    keep: bool


PhoneCommand = (
    Hello | Rename | QueueSong | RemoveEntry | MoveEntry
    | SetPaused | Skip | SetKey | SetVocal | SetAvOffset | ResolveRestart
)

# ---- TV reports ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TrackEnded:
    play: PlayId


@dataclass(frozen=True, slots=True)
class TrackFailed:
    play: PlayId
    reason: str


TvReport = TrackEnded | TrackFailed | ResolveRestart

# ---- facts from the shell -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SongReady:
    """From the Preparer: every file of this song is in the library. Idempotent."""

    song: SongId


@dataclass(frozen=True, slots=True)
class FillerPicked:
    token: PlayId
    """Echo of FillerRequest.token. A pick that arrives after a queued song already started is dropped."""
    song: SongMeta


@dataclass(frozen=True, slots=True)
class TvPresence:
    connected: bool


Fact = SongReady | FillerPicked | TvPresence

Input = PhoneCommand | TrackEnded | TrackFailed | Fact
"""What `reduce` accepts. (ResolveRestart appears in both PhoneCommand and TvReport; it is one type.)"""
