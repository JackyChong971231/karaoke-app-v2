"""Value types shared by the party core and the song side.

Leaf module: imports nothing from `karaoke`. Both `karaoke.party` and
`karaoke.songs` depend on it; it depends on neither.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NewType

SongId = NewType("SongId", str)
"""YouTube video ID of the chosen video. Also the library folder name."""

ArtistId = NewType("ArtistId", str)
"""YouTube channel ID. The same ID comes back in every language."""

SingerId = NewType("SingerId", str)
"""Random ID the phone generates once and keeps in localStorage."""


@dataclass(frozen=True, slots=True)
class ArtistRef:
    id: ArtistId
    name: str
    """Display name chosen by the catalog's language rule. Other spellings live in the library index."""


@dataclass(frozen=True, slots=True)
class SongMeta:
    """What the party needs to know about a song: identity and display.

    Built only by `Catalog.pick` or `Library.get`, never from phone-supplied text,
    so a title on the TV always came from YouTube Music or the library.
    """

    id: SongId
    title: str
    artist: ArtistRef
    duration_s: float
