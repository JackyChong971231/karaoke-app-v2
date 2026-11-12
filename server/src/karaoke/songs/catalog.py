"""Search and video choice. Owns every rule about turning YouTube Music results into SongMeta.

Read-only with respect to the party: phones query it over HTTP, never through the reducer. The pick-a-video
flow is per-phone UI state, so it lives on the phone; the server only remembers what it offered (`pick_id`)
so a phone can never inject its own title or artist.
"""

from __future__ import annotations

import asyncio
import re
import secrets
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Literal, NewType, Protocol

from karaoke.core import ArtistId, ArtistRef, SongId, SongMeta
from karaoke.songs.library import Library, search_key

PickId = NewType("PickId", str)
"""Opaque, server-issued. Maps to (online song, chosen video) in an in-memory LRU (1000 entries).
Lost on restart; the phone then gets 'search again'."""

OnlineKey = NewType("OnlineKey", str)
"""Opaque handle for an online song result (wraps the ATV video id). Not a SongId: identity is
only fixed once a video is chosen."""

Lang = Literal["zh_TW", "en"]
OFFICIAL_VIDEO = "MUSIC_VIDEO_TYPE_OMV"
CANDIDATES = 6
_MEMORY = 1000


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


@dataclass(frozen=True, slots=True)
class SongNames:
    artist_names: tuple[str, ...]
    alt_titles: tuple[str, ...]


class UnknownOnlineKey(LookupError):
    """The key came from a search this process no longer remembers (restart or LRU eviction)."""


class YouTubeMusic(Protocol):
    """Thin port over ytmusicapi (real) or fixtures (harness). Raw dicts stay behind it."""

    def search(self, query: str, language: str) -> list[dict]: ...  # type: ignore[type-arg]
    def videos(self, query: str) -> list[dict]: ...  # type: ignore[type-arg]
    def artist(self, artist: ArtistId, language: str) -> dict: ...  # type: ignore[type-arg]
    def track(self, video: SongId, language: str) -> dict | None: ...  # type: ignore[type-arg]


class YTMusicPort:
    """The real port. Search is unfiltered because filter="songs" returns nothing with language zh_TW."""

    def __init__(self, region: str = "HK") -> None:
        self._region = region
        self._clients: dict[str, Any] = {}

    def _yt(self, language: str) -> Any:
        if language not in self._clients:
            from ytmusicapi import YTMusic
            self._clients[language] = YTMusic(language=language, location=self._region)
        return self._clients[language]

    def search(self, query: str, language: str) -> list[dict]:  # type: ignore[type-arg]
        return list(self._yt(language).search(query, limit=20))

    def videos(self, query: str) -> list[dict]:  # type: ignore[type-arg]
        return list(self._yt("en").search(query, filter="videos", limit=20))

    def artist(self, artist: ArtistId, language: str) -> dict:  # type: ignore[type-arg]
        return dict(self._yt(language).get_artist(artist))

    def track(self, video: SongId, language: str) -> dict | None:  # type: ignore[type-arg]
        tracks = self._yt(language).get_watch_playlist(video, limit=1).get("tracks") or []
        return dict(tracks[0]) if tracks and tracks[0].get("videoId") == video else None


# ---- pure rules ----

_CJK = re.compile(r"[぀-ヿ㐀-鿿豈-﫿가-힣]")
_EDITION = re.compile(r"\s*[(（\[【]|\s+[-–]\s+|\s+(?:AIR|in [A-G])\b")


def has_cjk(text: str) -> bool:
    return bool(_CJK.search(text))


def display_language(zh_title: str, en_title: str | None) -> Lang:
    """zh_TW translates Western songs ("Complicated" -> 超複雜), so the en title wins exactly when it has
    no CJK and the zh_TW title does. The artist name follows the same choice."""
    if en_title and not has_cjk(en_title) and has_cjk(zh_title):
        return "en"
    return "zh_TW"


def core_title(title: str) -> str:
    """The title before any edition tag: "陀飛輪 (Live)" -> "陀飛輪"."""
    return _EDITION.split(title)[0].strip() or title.strip()


def is_official_video(video: dict, core_titles: tuple[str, ...], artist: ArtistId) -> bool:  # type: ignore[type-arg]
    """The strict rule. Loosening the artist check accepted a parody medley and a piano cover."""
    title = search_key(video.get("title") or "")
    return (
        video.get("videoType") == OFFICIAL_VIDEO
        and any(c and search_key(c) in title for c in core_titles)
        and any(a.get("id") == artist for a in video.get("artists") or [])
    )


def _seconds(r: dict) -> float:  # type: ignore[type-arg]
    if r.get("duration_seconds"):
        return float(r["duration_seconds"])
    parts = str(r.get("duration") or "").split(":")
    try:
        total = 0.0
        for p in parts:
            total = total * 60 + float(p)
        return total
    except ValueError:
        return 0.0


def _thumbnail(r: dict) -> str:  # type: ignore[type-arg]
    thumbs = r.get("thumbnails") or []
    if thumbs:
        return str(max(thumbs, key=lambda t: t.get("width", 0)).get("url", ""))
    return f"https://i.ytimg.com/vi/{r.get('videoId')}/hqdefault.jpg" if r.get("videoId") else ""


@dataclass(frozen=True, slots=True)
class _Seen:
    """One online song as both languages described it."""

    key: OnlineKey
    zh_title: str
    en_title: str | None
    artist_id: ArtistId
    zh_artist: str
    en_artist: str | None
    duration_s: float
    thumbnail_url: str
    spellings: tuple[str, ...] = ()
    """Every name either language gave this artist id, from any result type."""

    def lang(self) -> Lang:
        return display_language(self.zh_title, self.en_title)

    def public(self) -> OnlineSong:
        en = self.lang() == "en"
        title = self.en_title if en and self.en_title else self.zh_title
        artist = self.en_artist if en and self.en_artist else self.zh_artist
        return OnlineSong(self.key, title, ArtistRef(self.artist_id, artist), self.duration_s, self.thumbnail_url)

    def names(self) -> SongNames:
        return SongNames(_unique(self.zh_artist, self.en_artist, *self.spellings), _unique(self.zh_title, self.en_title))


def _unique(*xs: str | None) -> tuple[str, ...]:
    return tuple(dict.fromkeys(x for x in xs if x))


def _songs(results: list[dict]) -> list[dict]:  # type: ignore[type-arg]
    return [r for r in results
            if r.get("resultType") == "song" and r.get("videoId") and (r.get("artists") or [{}])[0].get("id")]


def pair_results(zh: list[dict], en: list[dict]) -> list[_Seen]:  # type: ignore[type-arg]
    """Song results from the zh_TW search, each paired with the en result for the same video."""
    en_by_id = {r["videoId"]: r for r in _songs(en)}
    spellings: dict[str, list[str]] = {}
    for r in [*zh, *en]:
        named = [(a.get("id"), a.get("name")) for a in r.get("artists") or []]
        if r.get("resultType") == "artist":
            named.append((r.get("browseId"), r.get("artist")))
        for artist_id, name in named:
            if artist_id and name and name not in spellings.setdefault(artist_id, []):
                spellings[artist_id].append(name)
    seen: list[_Seen] = []
    for r in _songs(zh):
        e = en_by_id.get(r["videoId"])
        a = r["artists"][0]
        e_artist = next((x["name"] for x in (e or {}).get("artists") or [] if x.get("id") == a["id"]), None)
        seen.append(_Seen(OnlineKey(r["videoId"]), r.get("title") or "", e.get("title") if e else None, ArtistId(a["id"]),
                          a.get("name") or "", e_artist, _seconds(r) or _seconds(e or {}), _thumbnail(r),
                          tuple(spellings.get(a["id"], ()))))
    return seen


class _Lru(OrderedDict[str, Any]):
    def put(self, key: str, value: Any) -> None:
        self[key] = value
        self.move_to_end(key)
        while len(self) > _MEMORY:
            self.popitem(last=False)


class Catalog:
    def __init__(self, library: Library, yt: YouTubeMusic) -> None:
        self._library = library
        self._yt = yt
        self._seen = _Lru()
        self._picks = _Lru()
        self._names = _Lru()

    async def search(self, query: str) -> SearchResult:
        """Library hits plus online song results."""
        lib = tuple(LibraryHit(r.meta, r.lyrics_source == "transcribed") for r in self._library.search(query))
        online: tuple[OnlineSong, ...] | OnlineUnavailable
        try:
            zh, en = await asyncio.gather(asyncio.to_thread(self._yt.search, query, "zh_TW"),
                                          asyncio.to_thread(self._yt.search, query, "en"))
            seen = pair_results(zh, en)
            # Results with no parseable song at all mean YouTube Music changed its format.
            online = OnlineUnavailable("format changed") if zh and not seen and not _songs(en) else self._remember(seen)
        except Exception as e:
            online = OnlineUnavailable(f"search failed: {type(e).__name__}")
        return SearchResult(lib, online)

    def _remember(self, seen: list[_Seen]) -> tuple[OnlineSong, ...]:
        out = []
        for s in seen:
            self._seen.put(s.key, s)
            if not self._in_library(s):
                out.append(s.public())
        return tuple(out)

    def _in_library(self, s: _Seen) -> bool:
        entry = self._library.artist(s.artist_id)
        if not entry:
            return False
        keys = {search_key(t) for t in (s.zh_title, s.en_title) if t}
        return any(search_key(m.title) in keys for m in entry.songs)

    async def artist(self, artist: ArtistId) -> ArtistPage:
        entry = self._library.artist(artist)
        lib = tuple(LibraryHit(m, self._flagged(m.id)) for m in entry.songs) if entry else ()
        try:
            zh, en = await asyncio.gather(asyncio.to_thread(self._yt.artist, artist, "zh_TW"),
                                          asyncio.to_thread(self._yt.artist, artist, "en"))
            zh_songs = [{**r, "resultType": "song"} for r in (zh.get("songs") or {}).get("results") or []]
            en_songs = [{**r, "resultType": "song"} for r in (en.get("songs") or {}).get("results") or []]
            seen = [s for s in pair_results(zh_songs, en_songs) if s.artist_id == artist]
            online: tuple[OnlineSong, ...] | OnlineUnavailable = self._remember(seen)
            en_votes = sum(s.lang() == "en" for s in seen)
            name = en.get("name") if en_votes * 2 > len(seen) and en.get("name") else zh.get("name")
            ref = ArtistRef(artist, str(name or (entry.ref.name if entry else "")))
        except Exception as e:
            online = OnlineUnavailable(f"artist lookup failed: {type(e).__name__}")
            ref = entry.ref if entry else ArtistRef(artist, "")
        return ArtistPage(ref, lib, online)

    def _flagged(self, song: SongId) -> bool:
        r = self._library.get(song)
        return bool(r and r.lyrics_source == "transcribed")

    async def resolve_video(self, song: OnlineKey) -> VideoResolution:
        """Find the official music video, else offer candidates. Raises UnknownOnlineKey for a key
        this process never returned (the phone shows 'search again')."""
        s: _Seen | None = self._seen.get(song)
        if s is None:
            raise UnknownOnlineKey(song)
        cores = _unique(core_title(s.zh_title), s.en_title and core_title(s.en_title))
        videos = [v for v in await asyncio.to_thread(self._yt.videos, f"{s.zh_artist} {cores[0]}") if v.get("videoId")]
        official = next((v for v in videos if is_official_video(v, cores, s.artist_id)), None)
        if official:
            return OfficialVideo(self._pick(s, official))
        return ChooseVideo(tuple(
            VideoCandidate(self._pick(s, v), SongId(v["videoId"]), v.get("title") or "",
                           ", ".join(a.get("name", "") for a in v.get("artists") or []), _thumbnail(v), _seconds(v))
            for v in videos[:CANDIDATES]
        ))

    async def identify(self, video: SongId) -> OnlineKey | None:
        """The song a known official video belongs to, from YouTube Music's own record of that video rather
        than a text search. Text search guessed the wrong song for titles v1 had already pinned to a video id.
        None for fan uploads, whose record names the uploader instead of the artist."""
        try:
            zh, en = await asyncio.gather(asyncio.to_thread(self._yt.track, video, "zh_TW"),
                                          asyncio.to_thread(self._yt.track, video, "en"))
        except Exception:
            return None
        # A fan upload's record is its raw video title and the uploader's channel, not the song and artist.
        if not zh or zh.get("videoType") == "MUSIC_VIDEO_TYPE_UGC":
            return None
        def as_song(t: dict | None) -> list[dict]:  # type: ignore[type-arg]
            return [{**t, "resultType": "song", "duration": t.get("length"),
                     "thumbnails": t.get("thumbnail") or t.get("thumbnails")}] if t else []
        seen = pair_results(as_song(zh), as_song(en))
        if not seen:
            return None
        self._seen.put(seen[0].key, seen[0])
        return seen[0].key

    def pick_video(self, song: OnlineKey, video: SongId) -> PickId:
        """The song's identity on a video the caller already knows, such as the v1 video an import reuses."""
        s: _Seen | None = self._seen.get(song)
        if s is None:
            raise UnknownOnlineKey(song)
        return self._pick(s, {"videoId": video})

    def _pick(self, s: _Seen, video: dict) -> PickId:  # type: ignore[type-arg]
        pub = s.public()
        meta = SongMeta(SongId(video["videoId"]), pub.title, pub.artist, _seconds(video) or s.duration_s)
        pick = PickId(secrets.token_urlsafe(9))
        self._picks.put(pick, meta)
        self._names.put(meta.id, s.names())
        return pick

    def pick(self, pick: PickId) -> SongMeta | None:
        """Resolve a pick into the song's identity. SongMeta.id = the chosen VIDEO's id."""
        meta: SongMeta | None = self._picks.get(pick)
        return meta

    async def describe(self, song: SongMeta) -> SongNames:
        """Every artist spelling and alternate title for song.json, so either name finds the song later.
        Served from what search already saw; after a restart it re-searches `artist + title` in both languages.
        The Preparer calls this once per song, before install."""
        known: SongNames | None = self._names.get(song.id)
        if known:
            return known
        fallback = SongNames((song.artist.name,), (song.title,))
        try:
            q = f"{song.artist.name} {core_title(song.title)}"
            zh, en = await asyncio.gather(asyncio.to_thread(self._yt.search, q, "zh_TW"),
                                          asyncio.to_thread(self._yt.search, q, "en"))
        except Exception:
            return fallback
        title = search_key(song.title)
        mine = [s for s in pair_results(zh, en) if s.artist_id == song.artist.id]
        same = [s for s in mine if title in {search_key(t) for t in (s.zh_title, s.en_title) if t}]
        best = next(iter(same or mine), None)
        if best is None:
            return fallback
        n = best.names()
        return SongNames(_unique(song.artist.name, *n.artist_names),
                         _unique(song.title, *(n.alt_titles if same else ())))
