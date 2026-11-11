"""Search and video choice. Owns every rule about turning YouTube Music results into SongMeta.

Read-only with respect to the party: phones query it over HTTP, never through the reducer. The pick-a-video
flow is per-phone UI state, so it lives on the phone; the server only remembers what it offered (`pick_id`)
so a phone can never inject its own title or artist.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NewType, Protocol

from karaoke.core import ArtistId, ArtistRef, SongId, SongMeta
from karaoke.songs.library import Library

PickId = NewType("PickId", str)
"""Opaque, server-issued. Maps to (online song, chosen video) in an in-memory LRU (1000 entries).
Lost on restart; the phone then gets 'search again'."""

OnlineKey = NewType("OnlineKey", str)
"""Opaque handle for an online song result (wraps the ATV video id). Not a SongId: identity is
only fixed once a video is chosen."""


@dataclass(frozen=True, slots=True)
class OnlineSong:
    key: OnlineKey
    title: str
    """Display title per the language rule: the `en` title when it has no CJK and the zh_TW title does,
    else the zh_TW title."""
    artist: ArtistRef
    duration_s: float
    thumbnail_url: str


@dataclass(frozen=True, slots=True)
class LibraryHit:
    song: SongMeta
    lyrics_flagged: bool


@dataclass(frozen=True, slots=True)
class OnlineUnavailable:
    reason: str


@dataclass(frozen=True, slots=True)
class SearchResult:
    library: tuple[LibraryHit, ...]
    online: tuple[OnlineSong, ...] | OnlineUnavailable
    """Online songs already in the library (same artist id + normalized title) are dropped here."""


@dataclass(frozen=True, slots=True)
class ArtistPage:
    artist: ArtistRef
    library: tuple[LibraryHit, ...]
    online: tuple[OnlineSong, ...] | OnlineUnavailable


@dataclass(frozen=True, slots=True)
class VideoCandidate:
    pick: PickId
    video_id: SongId
    title: str
    channel: str
    thumbnail_url: str
    duration_s: float


@dataclass(frozen=True, slots=True)
class OfficialVideo:
    """The strict rule found exactly the official music video. The phone queues it with no question."""

    pick: PickId


@dataclass(frozen=True, slots=True)
class ChooseVideo:
    """No official video. Top video results with thumbnails; the singer taps one."""

    candidates: tuple[VideoCandidate, ...]


VideoResolution = OfficialVideo | ChooseVideo


class YouTubeMusic(Protocol):
    """Thin port over ytmusicapi (real) or fixtures (harness). Raw dicts stay behind it."""

    def search(self, query: str, language: str) -> list[dict]: ...
    def videos(self, query: str) -> list[dict]: ...
    def artist(self, artist: ArtistId, language: str) -> dict: ...


class Catalog:
    def __init__(self, library: Library, yt: YouTubeMusic) -> None:
        raise NotImplementedError

    async def search(self, query: str) -> SearchResult:
        """Library hits plus online song results.

        TODO pseudocode:
            lib = library.search(query)
            try:
                zh, en = gather(yt.search(query, "zh_TW"), yt.search(query, "en"))   # UNFILTERED: filter="songs" is empty in zh_TW
                songs = [r for r in zh if r.resultType == "song" and r.artists]
                pair each with en result of same videoId for the alternate title / artist spelling
                if not songs and query looks common: return OnlineUnavailable("format changed")   # spec integrations table
            except Exception: online = OnlineUnavailable("search failed")
        """
        raise NotImplementedError

    async def artist(self, artist: ArtistId) -> ArtistPage: raise NotImplementedError

    async def resolve_video(self, song: OnlineKey) -> VideoResolution:
        """Find the official music video, else offer candidates.

        TODO pseudocode (strict rule, technical spec "Pick the music video"):
            core = title before any edition tag ("(Live)", "AIR (Day Version)", " - ...")
            for v in yt.videos(f"{artist.name} {core}"):
                if v.videoType == "MUSIC_VIDEO_TYPE_OMV" and core.lower() in v.title.lower()
                   and any(a.id == artist.id for a in v.artists):
                    return OfficialVideo(remember(song, v))
            return ChooseVideo(top 6 of the same results, each remembered)
        Rule 3 (artist id) is not loosened: loosening produced a parody medley and a piano cover.
        """
        raise NotImplementedError

    def pick(self, pick: PickId) -> SongMeta | None:
        """Resolve a pick into the song's identity. SongMeta.id = the chosen VIDEO's id."""
        raise NotImplementedError

    async def describe(self, song: SongMeta) -> SongNames:
        """Every artist spelling and alternate title for song.json, so either name finds the song later.
        Served from what search already saw; after a restart it re-searches `artist + title` in both languages.
        The Preparer calls this once per song, before install."""
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class SongNames:
    artist_names: tuple[str, ...]
    alt_titles: tuple[str, ...]
