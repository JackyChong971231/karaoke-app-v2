"""Wire -> domain. The only place a contract command becomes a party Input.

Validation of shape happens in pydantic (contract.py). This module adds the two things pydantic cannot:
binding the sender's identity (from the connection, never from the message), and resolving song
references into SongMeta from server-side sources (library or catalog pick), never from the phone.
Value-range rules (key -6..6, vocal 0..1) stay in the reducer so they have one home.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import assert_never

from karaoke import contract as c
from karaoke.core import SingerId, SongId, SongMeta
from karaoke.party import (
    Before, End, EntryId, Front, Input, MoveEntry, PlayId, Position, QueueSong, RemoveEntry, Rename, ResolveRestart,
    SetAdvancedLyrics, SetAvOffset, SetKey, SetPaused, SetVocal, SetVocalOn, Skip, StepKey, TrackEnded, TrackFailed,
)
from karaoke.songs.catalog import Catalog, PickId
from karaoke.songs.library import Library
from karaoke.vocab import RejectReason


@dataclass(frozen=True, slots=True)
class Unresolvable:
    """The command references something the server cannot turn into a song (unknown library id,
    expired pick). Replied to the sender without reaching the reducer."""

    reason: RejectReason


def phone_input(cmd: c.PhoneCommand, by: SingerId, library: Library, catalog: Catalog,
                name: str | None = None, favourite: Callable[[SongId], SongMeta | None] = lambda _: None,
                ) -> Input | Unresolvable:
    """`by` is the phone (from the connection's address); `name` is the sending browser's current name;
    `favourite` looks a song up in the sending browser's favourites."""
    match cmd:
        case c.QueueFavouriteCmd(song_id=song_id):
            meta = favourite(SongId(song_id))
            return Unresolvable("unknown_entry") if meta is None else QueueSong(by, meta, name)
        case c.QueueLibraryCmd(song_id=song_id):
            rec = library.get(SongId(song_id))
            return Unresolvable("unknown_entry") if rec is None else QueueSong(by, rec.meta, name)
        case c.QueuePickCmd(pick_id=pick_id):
            meta = catalog.pick(PickId(pick_id))
            return Unresolvable("pick_expired") if meta is None else QueueSong(by, meta, name)
        case c.RemoveCmd(entry_id=entry_id):
            return RemoveEntry(by, EntryId(entry_id))
        case c.MoveCmd(entry_id=entry_id, to=to):
            return MoveEntry(by, EntryId(entry_id), _position(to))
        case c.SetPausedCmd(play_id=play_id, paused=paused):
            return SetPaused(by, PlayId(play_id), paused)
        case c.SkipCmd(play_id=play_id):
            return Skip(by, PlayId(play_id))
        case c.SetKeyCmd(play_id=play_id, semitones=semitones):
            return SetKey(by, PlayId(play_id), semitones)
        case c.StepKeyCmd(play_id=play_id, step=step):
            return StepKey(by, PlayId(play_id), step)
        case c.SetVocalCmd(level=level):
            return SetVocal(by, level)
        case c.SetVocalOnCmd(on=on):
            return SetVocalOn(by, on)
        case c.SetAvOffsetCmd(seconds=seconds):
            return SetAvOffset(by, seconds)
        case c.SetAdvancedLyricsCmd(on=on):
            return SetAdvancedLyrics(by, on)
        case c.RenameCmd(name=name):
            return Rename(by, name)
        case c.ResolveRestartCmd(keep=keep):
            return ResolveRestart(keep)
        case _:
            assert_never(cmd)


def tv_input(cmd: c.TvCommand) -> Input:
    match cmd:
        case c.TrackEndedCmd(play_id=play_id):
            return TrackEnded(PlayId(play_id))
        case c.TrackFailedCmd(play_id=play_id, reason=reason):
            return TrackFailed(PlayId(play_id), reason)
        case c.ResolveRestartCmd(keep=keep):
            return ResolveRestart(keep)
        case _:
            assert_never(cmd)


def _position(to: c.ToFront | c.ToEnd | c.ToBefore) -> Position:
    match to:
        case c.ToFront():
            return Front()
        case c.ToEnd():
            return End()
        case c.ToBefore(entry_id=entry_id):
            return Before(EntryId(entry_id))
        case _:
            assert_never(to)
