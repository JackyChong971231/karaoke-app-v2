"""Domain -> wire. Pure functions. The read boundary where per-owner state is merged:

    party state (reducer)  +  preparation board (Preparer)  +  last clock report (hub)  ->  view

Nothing here decides anything; it formats. A field a page needs that cannot be computed from these
three inputs is a sign the owner is missing a fact, not that a view should keep state.
"""

from __future__ import annotations

from collections.abc import Mapping

from karaoke import contract as c
from karaoke.core import SongId
from karaoke.party import PartyState
from karaoke.songs.prepare import Device, PrepStatus


def readiness(song: SongId, state: PartyState, board: Mapping[SongId, PrepStatus]) -> c.ReadyState | c.PreparingState | c.FailedState:
    """`state.ready` wins (it is what the reducer acts on); else the board's stage; else waiting."""
    raise NotImplementedError


def phone_view(rev: int, state: PartyState, board: Mapping[SongId, PrepStatus], device: Device,
               flagged: frozenset[SongId]) -> c.PhoneView:
    """`flagged` = songs whose lyrics.json source is 'transcribed' (from Library), for the 'may be wrong' badge."""
    raise NotImplementedError


def tv_view(rev: int, state: PartyState, resume_at: Mapping[int, float], join_url: str,
            flagged: frozenset[SongId]) -> c.TvView:
    """up_next = first queue entry (ready or not), per the spec 'the next song and its singer are shown'.
    resume_at = hub's last ClockReport position by play_id, so a reloaded TV continues where it was."""
    raise NotImplementedError
