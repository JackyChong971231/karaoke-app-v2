"""Browse by place: 香港 台灣 中國 日本 韓國 歐美 (spec 00-product.md "Browse for songs", 01-technical.md "Browse").

Each place is a page of 熱門 shelves: the place's YouTube Music chart, then a few playlists found by fixed searches.
Probed 2026-11-12: charts exist for HK, TW, JP, KR and US but not CN (YouTube is blocked there), and playlist search
returns label and chart lists (warnermusichk, KKBOX, Sony Music) mixed with fan lists.

A singer's place is the place whose shelves they appear on most, Cantonese playlists counting double for 香港. The
user's choice from the control page always wins. Both are kept in artist-places.json. Wikidata was tried and dropped:
it lists G.E.M. only as a PRC citizen born in Shanghai.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, get_args

from karaoke.core import ArtistId, ArtistRef
from karaoke.songs.catalog import Catalog, LibraryHit, OnlineSong, YouTubeMusic
from karaoke.songs.library import Library, search_key
from karaoke.vocab import PlaceId

log = logging.getLogger(__name__)
PLACE_IDS: tuple[PlaceId, ...] = get_args(PlaceId)
CACHE_S = 6 * 3600
SHELF_SIZE = 30
SINGERS_SHOWN = 30
_TRUSTED = ("warnermusic", "universal", "sony music", "kkbox", "redlist", "華納", "環球", "索尼", "emi", "avex")

_HAN = re.compile(r"[㐀-鿿豈-﫿]")
_KANA = re.compile(r"[぀-ヿ]")
_HANGUL = re.compile(r"[가-힣ᄀ-ᇿ]")


def _chinese(text: str) -> bool:
    """Chinese characters, and no kana or Hangul: Japanese titles share kanji with Chinese."""
    return bool(_HAN.search(text)) and not _HANGUL.search(text) and not _KANA.search(text)


def _not_hangul(text: str) -> bool:
    return not _HANGUL.search(text)


def _not_kana(text: str) -> bool:
    return not _KANA.search(text)


def _no_cjk(text: str) -> bool:
    return not (_HAN.search(text) or _KANA.search(text) or _HANGUL.search(text))


@dataclass(frozen=True, slots=True)
class Place:
    id: PlaceId
    label: str
    chart: str | None
    """YouTube Music chart country, or None (mainland China has no chart)."""
    searches: tuple[str, ...]
    """Playlist searches; `{year}` becomes the current year."""
    keeps: Callable[[str], bool]
    """Keeps a track whose title plus artist passes, so a chart's songs from elsewhere drop out."""
    cantonese: bool = False
    """Its playlists are Cantonese, so appearing on them counts double for a singer's place."""
    hints: tuple[str, ...] = ()
    """Words a playlist title should contain, preferred over a label's general list. Without them 中國 picked
    the same pan-Chinese chart list as 台灣 (probed 2026-11-12)."""


PLACES: tuple[Place, ...] = (
    Place("hk", "香港", "HK", ("最新熱門廣東歌", "廣東歌 {year}"), _chinese, cantonese=True,
          hints=("廣東", "粵語", "广东", "粤语", "cantopop")),
    Place("tw", "台灣", "TW", ("KKBOX 華語 新歌 {year}", "台灣 華語 熱門 {year}"), _chinese, hints=("台灣", "台湾", "kkbox")),
    Place("cn", "中國", None, ("內地 流行歌 {year}", "抖音 熱歌 {year}"), _chinese,
          hints=("大陸", "大陆", "內地", "内地", "抖音", "中国")),
    Place("jp", "日本", "JP", ("J-Pop {year}",), _not_hangul),
    Place("kr", "韓國", "KR", ("K-Pop {year}",), _not_kana),
    Place("west", "歐美", "US", ("Pop hits {year}",), _no_cjk),
)
PLACE_BY_ID = {p.id: p for p in PLACES}


@dataclass(frozen=True, slots=True)
class Shelf:
    title: str
    items: tuple[LibraryHit | OnlineSong, ...]


@dataclass(frozen=True, slots=True)
class Singer:
    artist: ArtistRef
    photo_url: str


@dataclass(frozen=True, slots=True)
class PlacePage:
    place: Place
    shelves: tuple[Shelf, ...]
    library: tuple[LibraryHit, ...]
    singers: tuple[Singer, ...]
    online_ok: bool


# ---- where each singer is from ------------------------------------------------------------

_KNOWN: dict[PlaceId, tuple[str, ...]] = {
        "hk": ("G.E.M.", "鄧紫棋", "邓紫棋", "陳奕迅", "陈奕迅", "Eason Chan", "容祖兒", "Joey Yung", "衛蘭", "Janice Vidal",
               "張學友", "Jacky Cheung", "古巨基", "Leo Ku", "楊千嬅", "Miriam Yeung", "王菲", "Faye Wong", "張敬軒",
               "Hins Cheung", "MIRROR", "姜濤", "Keung To", "林家謙", "Terence Lam", "Dear Jane", "MC 張天賦",
               "MC Cheung Tinfu", "Supper Moment", "方大同", "Khalil Fong", "林峯", "Raymond Lam", "謝霆鋒",
               "Nicholas Tse", "陳蕾", "Panther Chan", "Gareth.T", "Kiri T", "Twins", "側田", "Justin Lo"),
        "tw": ("周杰倫", "Jay Chou", "五月天", "Mayday", "蔡依林", "Jolin Tsai", "張惠妹", "A-Mei", "A-Lin", "告五人",
               "Accusefive", "盧廣仲", "Crowd Lu", "田馥甄", "Hebe Tien", "S.H.E", "蕭敬騰", "Jam Hsiao", "張韶涵",
               "Angela Chang", "楊丞琳", "Rainie Yang", "玖壹壹", "宇宙人", "李宗盛", "伍佰", "Wu Bai", "動力火車"),
        "cn": ("薛之謙", "Joker Xue", "毛不易", "Mao Buyi", "周深", "Charlie Zhou Shen", "李榮浩", "Ronghao Li",
               "汪蘇瀧", "Silence Wang", "華晨宇", "Hua Chenyu", "張碧晨", "Diamond Zhang", "鄧超", "TFBOYS",
               "王源", "王俊凱", "易烊千璽", "時代少年團", "大颖dior", "DIOR 大穎"),
}
KNOWN_PLACES: dict[str, PlaceId] = {name.casefold(): place for place, names in _KNOWN.items() for name in names}
"""Singers who appear on more than one Chinese box and whose place the shelves get wrong. Probed 2026-11-12:
G.E.M. appears on both the HK and TW charts and on more TW lists, so counting shelves put her under 台灣. Matched
by any spelling the shelves show. The user's choice on the control page still wins."""

@dataclass
class _Artist:
    name: str
    counts: dict[str, float] = field(default_factory=dict)
    chosen: str | None = None
    photo: str = ""


@dataclass
class ArtistPlaces:
    """artist-places.json: per singer, how often they appear on each place's shelves, the user's choice, a photo."""

    path: Path
    _artists: dict[str, _Artist] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            doc = json.loads(self.path.read_text(encoding="utf-8"))
            self._artists = {k: _Artist(v["name"], dict(v.get("counts", {})), v.get("chosen"), v.get("photo", ""))
                             for k, v in doc["artists"].items()}
        except (ValueError, KeyError, TypeError) as e:
            bad = self.path.with_name(f"{self.path.name}.bad-{int(time.time())}")
            os.replace(self.path, bad)
            log.warning("artist-places.json was unreadable (%s); moved to %s", e, bad)

    def place_of(self, artist: ArtistId) -> PlaceId | None:
        a = self._artists.get(artist)
        if a is None:
            return None
        if a.chosen in PLACE_BY_ID:
            return a.chosen
        known = KNOWN_PLACES.get(a.name.casefold())
        if known is not None:
            return known
        best = max(a.counts.items(), key=lambda kv: kv[1], default=None)
        return best[0] if best and best[1] > 0 and best[0] in PLACE_BY_ID else None

    def definite(self, artist: ArtistRef) -> PlaceId | None:
        """The place only when it is certain: the user's choice or the list of known singers, never a shelf count."""
        a = self._artists.get(artist.id)
        if a is not None and a.chosen in PLACE_BY_ID:
            return a.chosen
        return KNOWN_PLACES.get(artist.name.casefold())

    def chosen(self, artist: ArtistId) -> bool:
        a = self._artists.get(artist)
        return a is not None and a.chosen is not None

    def choose(self, artist: ArtistRef, place: PlaceId | None) -> None:
        """The user's choice from the control page. None returns the singer to the shelf guess."""
        with self._lock:
            a = self._artists.setdefault(artist.id, _Artist(artist.name))
            a.chosen = place
            self._save()

    def recount(self, place: PlaceId, seen: dict[ArtistId, tuple[str, float]]) -> None:
        """Replace every singer's count for `place` with what the place's shelves show now."""
        with self._lock:
            for a in self._artists.values():
                a.counts.pop(place, None)
            for artist, (name, weight) in seen.items():
                a = self._artists.setdefault(artist, _Artist(name))
                a.counts[place] = weight
            self._save()

    def set_photo(self, artist: ArtistId, url: str) -> None:
        with self._lock:
            a = self._artists.get(artist)
            if a is not None and url and a.photo != url:
                a.photo = url
                self._save()

    def photo(self, artist: ArtistId) -> str:
        a = self._artists.get(artist)
        return a.photo if a else ""

    def singers(self, place: PlaceId) -> list[tuple[ArtistRef, float]]:
        """Singers of `place`, most seen first."""
        out = [(ArtistRef(ArtistId(k), a.name), a.counts.get(place, 0.0))
               for k, a in self._artists.items() if self.place_of(ArtistId(k)) == place]
        return sorted(out, key=lambda x: -x[1])

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        doc = {"version": 1, "artists": {k: {"name": a.name, "counts": a.counts, "chosen": a.chosen, "photo": a.photo}
                                         for k, a in self._artists.items()}}
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)


# ---- pages ------------------------------------------------------------------------------

def _thumb(d: dict[str, Any]) -> str:
    thumbs = d.get("thumbnails") or []
    return str(max(thumbs, key=lambda t: t.get("width", 0)).get("url", "")) if thumbs else ""


def _track_text(track: dict[str, Any]) -> str:
    return " ".join([track.get("title") or "", *((a.get("name") or "") for a in track.get("artists") or [])])


def pick_playlist(results: list[dict[str, Any]], hints: tuple[str, ...] = (), year: str = "") -> dict[str, Any] | None:
    """Narrowed in turn, each step only when something passes it: lists naming this year (熱門, not classics; a
    2018 KKBOX list was picked otherwise), lists whose title names the place, record label or chart owner lists."""
    usable = [r for r in results if r.get("browseId")]
    dated = [r for r in usable if year and year in str(r.get("title") or "")]
    usable = dated or usable
    named = [r for r in usable if any(h in str(r.get("title") or "").casefold() for h in hints)]
    usable = named or usable
    trusted = [r for r in usable if any(t in str(r.get("author") or "").casefold() for t in _TRUSTED)]
    return (trusted or usable)[0] if (trusted or usable) else None


def _artist(item: LibraryHit | OnlineSong) -> ArtistRef:
    return item.song.artist if isinstance(item, LibraryHit) else item.artist


class Browse:
    def __init__(self, catalog: Catalog, library: Library, yt: YouTubeMusic, places: ArtistPlaces,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._catalog = catalog
        self._library = library
        self._yt = yt
        self.places = places
        self._clock = clock
        self._cache: dict[PlaceId, tuple[float, tuple[Shelf, ...], bool]] = {}
        self._building: dict[PlaceId, asyncio.Task[tuple[tuple[Shelf, ...], bool]]] = {}
        self._photo_tasks: set[asyncio.Task[None]] = set()
        self._photo_tried: set[ArtistId] = set()

    async def page(self, place_id: PlaceId) -> PlacePage:
        place = PLACE_BY_ID[place_id]
        built, ok = await self._shelves(place)
        # A chart lists who is popular there, not who is from there: a song by a singer known to be from another
        # place is left out, so 中國 does not show Taiwanese singers. Applied here, so a user's choice counts at once.
        shelves = tuple(
            Shelf(sh.title, tuple(i for i in sh.items if self.places.definite(_artist(i)) in (None, place_id)))
            for sh in built
        )
        library: list[LibraryHit] = []
        for artist in self._library.artists():
            entry = self._library.artist(artist.id) if self.places.place_of(artist.id) == place_id else None
            for m in entry.songs if entry else ():
                rec = self._library.get(m.id)
                library.append(LibraryHit(m, rec is not None and rec.lyrics_source == "transcribed"))
        ranked = self.places.singers(place_id)[:SINGERS_SHOWN]
        singers = tuple(Singer(ref, self.places.photo(ref.id)) for ref, _ in ranked)
        self._fetch_photos([s.artist.id for s in singers if not s.photo_url])
        return PlacePage(place, shelves, tuple(library), singers, ok)

    async def _shelves(self, place: Place) -> tuple[tuple[Shelf, ...], bool]:
        hit = self._cache.get(place.id)
        if hit and self._clock() - hit[0] < CACHE_S:
            return hit[1], hit[2]
        task = self._building.get(place.id)
        if task is None:
            task = asyncio.create_task(self._build(place))
            self._building[place.id] = task
            task.add_done_callback(lambda _: self._building.pop(place.id, None))
        return await task

    async def _build(self, place: Place) -> tuple[tuple[Shelf, ...], bool]:
        year = time.strftime("%Y")
        jobs: list[asyncio.Future[tuple[str, list[dict[str, Any]], float]]] = []
        if place.chart:
            jobs.append(asyncio.ensure_future(self._chart(place.chart)))
        for q in place.searches:
            jobs.append(asyncio.ensure_future(
                self._playlist(q.format(year=year), 2.0 if place.cantonese else 1.0, place.hints)))
        results = await asyncio.gather(*jobs, return_exceptions=True)
        shelves: list[Shelf] = []
        seen: dict[ArtistId, tuple[str, float]] = {}
        failed = 0
        for r in results:
            if isinstance(r, BaseException):
                failed += 1
                log.warning("browse %s: a shelf failed: %r", place.id, r)
                continue
            title, tracks, weight = r
            if any(sh.title == title for sh in shelves):
                continue  # Two searches found the same playlist.
            items: list[LibraryHit | OnlineSong] = []
            ids: set[str] = set()
            for t in tracks:
                # Fan uploads name the uploader as the artist ("Only Clean Edits"), so only official videos
                # and songs are kept.
                if t.get("videoType") == "MUSIC_VIDEO_TYPE_UGC" or not place.keeps(_track_text(t)):
                    continue
                item = self._catalog.shelf_item(t)
                if item is None:
                    continue
                song_title, artist_ref = (item.song.title, item.song.artist) if isinstance(item, LibraryHit)                     else (item.title, item.artist)
                key = f"{artist_ref.id}|{search_key(song_title)}"
                if key in ids:
                    continue
                ids.add(key)
                items.append(item)
                name, count = seen.get(artist_ref.id, (artist_ref.name, 0.0))
                seen[artist_ref.id] = (name, count + weight)
                if len(items) >= SHELF_SIZE:
                    break
            if items:
                shelves.append(Shelf(title, tuple(items)))
        ok = failed < len(results)
        if seen:
            await asyncio.to_thread(self.places.recount, place.id, seen)
        if ok:
            self._cache[place.id] = (self._clock(), tuple(shelves), ok)
        return tuple(shelves), ok

    async def _chart(self, country: str) -> tuple[str, list[dict[str, Any]], float]:
        charts = await asyncio.to_thread(self._yt.charts, country)
        videos = [v for v in charts.get("videos") or [] if v.get("playlistId")]
        if not videos:
            raise LookupError(f"no video chart for {country}")
        top = videos[-1]  # The last video chart is the Top 100; the first is a short trending list.
        for a in charts.get("artists") or []:
            if a.get("browseId") and _thumb(a):
                self.places.set_photo(ArtistId(a["browseId"]), _thumb(a))
        tracks = await asyncio.to_thread(self._yt.playlist, top["playlistId"], SHELF_SIZE * 2)
        return str(top.get("title") or "熱門"), tracks, 1.0

    async def _playlist(self, query: str, weight: float,
                        hints: tuple[str, ...]) -> tuple[str, list[dict[str, Any]], float]:
        found = pick_playlist(await asyncio.to_thread(self._yt.playlists, query), hints, time.strftime("%Y"))
        if found is None:
            raise LookupError(f"no playlist for {query!r}")
        tracks = await asyncio.to_thread(self._yt.playlist, found["browseId"], SHELF_SIZE * 2)
        return str(found.get("title") or query), tracks, weight

    def _fetch_photos(self, artists: list[ArtistId]) -> None:
        """Singer photos come from each artist's page, fetched in the background so the page shows at once."""
        async def fetch(artist: ArtistId) -> None:
            try:
                d = await asyncio.to_thread(self._yt.artist, artist, "zh_TW")
                await asyncio.to_thread(self.places.set_photo, artist, _thumb(d))
            except Exception as e:
                log.info("no photo for %s: %r", artist, e)

        for artist in [a for a in artists if a not in self._photo_tried][:12]:
            self._photo_tried.add(artist)
            task = asyncio.create_task(fetch(artist))
            self._photo_tasks.add(task)
            task.add_done_callback(self._photo_tasks.discard)
