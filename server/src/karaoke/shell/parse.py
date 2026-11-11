"""Wire -> domain. The only place a contract command becomes a party Input.

Validation of shape happens in pydantic (contract.py). This module adds the two things pydantic cannot:
binding the sender's identity (from the connection, never from the message), and resolving song
references into SongMeta from server-side sources (library or catalog pick), never from the phone.
Value-range rules (key -6..6, vocal 0..1) stay in the reducer so they have one home.
"""

from __future__ import annotations

from dataclasses import dataclass

from karaoke import contract as c
from karaoke.core import SingerId
from karaoke.party import inputs as i
from karaoke.songs.catalog import Catalog
from karaoke.songs.library import Library
from karaoke.vocab import RejectReason


@dataclass(frozen=True, slots=True)
class Unresolvable:
    """The command references something the server cannot turn into a song (unknown library id,
    expired pick). Replied to the sender without reaching the reducer."""

    reason: RejectReason


def phone_input(cmd: c.PhoneCommand, by: SingerId, library: Library, catalog: Catalog) -> i.Input | Unresolvable:
    """TODO pseudocode:
        match cmd:
            QueueLibraryCmd(song_id): rec = library.get(song_id); rec is None -> Unresolvable("unknown_entry")
                                      -> i.QueueSong(by, rec.meta)
            QueuePickCmd(pick_id):    meta = catalog.pick(pick_id); None -> Unresolvable("pick_expired")
                                      -> i.QueueSong(by, meta)
            MoveCmd(entry_id, to):    i.MoveEntry(by, EntryId(entry_id), Front()|End()|Before(EntryId(x)))
            ... one line each for the rest; assert_never on the default branch.
    """
    raise NotImplementedError


def tv_input(cmd: c.TvCommand) -> i.Input:
    raise NotImplementedError
