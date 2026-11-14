"""Lyrics from lyrics websites, for singers to read on their own phone (spec "Read the lyrics from a lyrics site").

View only: nothing here touches the TV's lyrics, preparation, or the library. Each site is read by a pure
parser over the page it returns (unit-tested on saved page shapes) plus one blocking HTTP fetch, so the
`LyricsSites` port is the only place the internet is touched, and the fake world swaps it for canned answers.

    LRCLIB    /api/search JSON                 -> text, no page link (LRCLIB has no song pages)
    Genius    /api/search/multi JSON -> page   -> text of the data-lyrics-container blocks
    Uta-Net   /search/ HTML -> /song/<n>/      -> text of #kashi_area
    KKBOX     /tw/tc/search HTML (top result)  -> link only: song pages answer with a bot check (AWS WAF)
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from html.parser import HTMLParser
from typing import Protocol

from opencc import OpenCC

from karaoke.core import SongId
from karaoke.songs.catalog import core_title
from karaoke.songs.library import Library, search_key
from karaoke.vocab import LyricsSite

log = logging.getLogger(__name__)

TIMEOUT_S = 10
CACHE_S = 6 * 3600
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"

FIRST_SITE: dict[str, LyricsSite] = {"zh": "kkbox", "ja": "utanet", "en": "genius"}
ALL_SITES: tuple[LyricsSite, ...] = ("kkbox", "lrclib", "utanet", "genius")


# ---- answers ----

@dataclass(frozen=True, slots=True)
class SiteText:
    text: str
    page_url: str | None


@dataclass(frozen=True, slots=True)
class SiteLink:
    """The site cannot be read by the app, only opened in the phone's browser."""
    page_url: str
    found: bool
    """True: the song's own page. False: the site's search results for the song."""


@dataclass(frozen=True, slots=True)
class SiteNone:
    """The site answered and has no lyrics for this song."""


@dataclass(frozen=True, slots=True)
class SiteDown:
    """Network error, timeout, or a page shape the parser does not know."""


SiteAnswer = SiteText | SiteLink | SiteNone | SiteDown


@dataclass(frozen=True, slots=True)
class SongQuery:
    titles: tuple[str, ...]
    """The library title first, then other spellings."""
    artists: tuple[str, ...]
    """Every known spelling of the singer's name."""
    language: str


def site_order(language: str) -> tuple[LyricsSite, ...]:
    """Every site, with the song language's own site first (spec: KKBOX for Chinese, Uta-Net for Japanese,
    Genius for English, LRCLIB otherwise)."""
    first = FIRST_SITE.get(language, "lrclib")
    return (first, *(s for s in ALL_SITES if s != first))


def language_of(language: str, title: str) -> str:
    if language:
        return language
    if re.search(r"[぀-ヿ]", title):
        return "ja"
    if re.search(r"[가-힣]", title):
        return "ko"
    if re.search(r"[㐀-鿿]", title):
        return "zh"
    return "en"


# ---- matching helpers ----

def _keys(texts: Sequence[str]) -> list[str]:
    return [k for k in (search_key(core_title(t)) for t in texts if t) if k]


def title_matches(found: str, titles: Sequence[str]) -> bool:
    k = search_key(core_title(found))
    return bool(k) and any(t in k or k in t for t in _keys(titles))


def artist_matches(found: str, artists: Sequence[str]) -> bool:
    k = search_key(found)
    return bool(k) and any(a and (a in k or k in a) for a in (search_key(x) for x in artists))


@lru_cache(maxsize=1)
def _s2hk() -> OpenCC:
    return OpenCC("s2hk")


_ZERO_WIDTH = re.compile("[\u200b\u200c\u200d\ufeff]")
_ODD_SPACE = re.compile("[\u00a0\u2000-\u200a\u202f\u205f\u3000]")


def tidy(text: str, language: str) -> str:
    """Trim each line, collapse runs of blank lines to one, and show Chinese in Traditional script. Zero-width
    characters go, and odd-width spaces (Genius's U+2005, Japanese full-width spaces) become plain spaces."""
    text = _ODD_SPACE.sub(" ", _ZERO_WIDTH.sub("", text))
    lines = [line.strip() for line in text.replace("\r", "").split("\n")]
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    result = "\n".join(out).strip()
    return str(_s2hk().convert(result)) if language == "zh" else result


# ---- LRCLIB ----

_LRC_TAG = re.compile(r"^(\s*\[[^\]]*\])+")


def parse_lrclib(hits: object, q: SongQuery) -> str | None:
    if not isinstance(hits, list):
        raise ValueError("LRCLIB answer is not a list")
    usable = [h for h in hits if isinstance(h, dict) and not h.get("instrumental")
              and (h.get("plainLyrics") or h.get("syncedLyrics")) and title_matches(h.get("trackName") or "", q.titles)
              and artist_matches(h.get("artistName") or "", q.artists)]
    if not usable:
        return None
    best = usable[0]
    if best.get("plainLyrics"):
        return str(best["plainLyrics"])
    return "\n".join(_LRC_TAG.sub("", line) for line in str(best["syncedLyrics"]).splitlines())


# ---- Genius ----

def parse_genius_search(data: object, q: SongQuery) -> str | None:
    """The page URL of the first song hit whose title and singer match. A title alone is not enough: another
    singer's song of the same name is a wrong answer. Genius's own translation pages are skipped."""
    if not isinstance(data, dict):
        raise ValueError("Genius answer is not an object")
    songs: list[dict] = []  # type: ignore[type-arg]
    for section in data["response"]["sections"]:
        for hit in section.get("hits", []):
            r = hit.get("result") or {}
            if hit.get("type") == "song" and r.get("url") and r not in songs:
                songs.append(r)
    def singer(r: dict) -> str:  # type: ignore[type-arg]
        return str((r.get("primary_artist") or {}).get("name", ""))

    matching = [r for r in songs if title_matches(r.get("title") or "", q.titles)
                and "genius" not in singer(r).casefold() and artist_matches(singer(r), q.artists)]
    if not matching:
        return None
    return str(matching[0]["url"])


_VOID = frozenset({"br", "img", "hr", "input", "meta", "link", "wbr", "source", "area", "col", "embed"})


class _GeniusLyrics(HTMLParser):
    """Text of every <div data-lyrics-container="true">, skipping elements marked data-exclude-from-selection
    (the contributors header and in-read ads). <br> becomes a line break."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[list[str]] = []
        self._depth = 0          # open elements inside the current container, 0 = outside
        self._skip_at = 0        # depth at which an excluded element opened, 0 = not skipping

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if self._depth == 0:
            if tag == "div" and a.get("data-lyrics-container") == "true":
                self._depth = 1
                self.blocks.append([])
            return
        if tag == "br":
            if not self._skip_at:
                self.blocks[-1].append("\n")
            return
        if tag in _VOID:
            return
        self._depth += 1
        if not self._skip_at and a.get("data-exclude-from-selection") == "true":
            self._skip_at = self._depth

    def handle_endtag(self, tag: str) -> None:
        if self._depth == 0 or tag in _VOID:
            return
        if self._skip_at == self._depth:
            self._skip_at = 0
        self._depth -= 1

    def handle_data(self, data: str) -> None:
        if self._depth and not self._skip_at:
            self.blocks[-1].append(data)


def parse_genius_page(page: str) -> str | None:
    p = _GeniusLyrics()
    p.feed(page)
    p.close()
    if not p.blocks:
        raise ValueError("Genius page has no lyrics container")
    text = "\n".join("".join(b) for b in p.blocks)
    return text if text.strip() else None


# ---- Uta-Net ----

_UTANET_ROW = re.compile(
    r'<a href="/song/(\d+)/"[^>]*>\s*<span class="[^"]*songlist-title[^"]*">(.*?)</span>.*?'
    r'<span class="[^"]*utaidashi[^"]*">(.*?)</span>', re.S)
_UTANET_KASHI = re.compile(r'<div id="kashi_area"[^>]*>(.*?)</div>', re.S)
_TAG = re.compile(r"<[^>]+>")
_BR = re.compile(r"<br\s*/?>", re.I)


def parse_utanet_search(page: str, q: SongQuery) -> str | None:
    """The song page of the first row whose title and singer match."""
    rows = [(n, html.unescape(_TAG.sub("", t)), html.unescape(_TAG.sub("", a))) for n, t, a in _UTANET_ROW.findall(page)]
    titled = [r for r in rows if title_matches(r[1], q.titles)]
    if not titled:
        return None
    best = next((r for r in titled if artist_matches(r[2], q.artists)), None)
    if best is None:
        return None
    return f"https://www.uta-net.com/song/{best[0]}/"


def parse_utanet_song(page: str) -> str | None:
    m = _UTANET_KASHI.search(page)
    if m is None:
        raise ValueError("Uta-Net page has no #kashi_area")
    text = html.unescape(_TAG.sub("", _BR.sub("\n", m.group(1))))
    return text if text.strip() else None


# ---- KKBOX ----

_KKBOX_TOP = re.compile(r'<div class="top-result">(.*?)(?:<div class="single-type|\Z)', re.S)
_KKBOX_SLOT = re.compile(r'<a\s+slot="(song-name|artist-name)"[^>]*?title="([^"]*)"[^>]*?href="([^"]*)"'
                         r'|<a\s+slot="(song-name|artist-name)"[^>]*?href="([^"]*)"[^>]*?title="([^"]*)"', re.S)


def kkbox_search_url(q: SongQuery) -> str:
    words = " ".join(x for x in (core_title(q.titles[0]) if q.titles else "", q.artists[0] if q.artists else "") if x)
    return f"https://www.kkbox.com/tw/tc/search?q={urllib.parse.quote(words)}"


def parse_kkbox_search(page: str, q: SongQuery) -> str | None:
    """The top result's song page, when the top result is a song with this title and singer. KKBOX renders
    only the top result into the page; the rest of the list loads by script."""
    m = _KKBOX_TOP.search(page)
    if m is None or "<song-li" not in m.group(1):
        return None  # the top result is a singer, album, or playlist
    slots: dict[str, tuple[str, str]] = {}
    for s1, t1, h1, s2, h2, t2 in _KKBOX_SLOT.findall(m.group(1)):
        slots[s1 or s2] = (html.unescape(t1 or t2), html.unescape(h1 or h2))
    song, artist = slots.get("song-name"), slots.get("artist-name")
    if song is None or artist is None or not song[1].startswith("https://www.kkbox.com/"):
        return None
    if title_matches(song[0], q.titles) and artist_matches(artist[0], q.artists):
        return song[1]
    return None


# ---- the port ----

class LyricsSites(Protocol):
    async def lookup(self, site: LyricsSite, q: SongQuery) -> SiteAnswer: ...


Fetch = Callable[[str], str]
"""Blocking GET returning the body as text. Raises on any HTTP or network error."""


def http_get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept-Language": "zh-TW,zh;q=0.9,ja;q=0.8,en;q=0.7"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        if r.status != 200:
            raise urllib.error.HTTPError(url, r.status, "not 200", r.headers, None)
        body: bytes = r.read()
        return body.decode(r.headers.get_content_charset() or "utf-8", errors="replace")


class WebLyricsSites:
    """The real sites."""

    def __init__(self, fetch: Fetch = http_get) -> None:
        self._fetch = fetch

    async def lookup(self, site: LyricsSite, q: SongQuery) -> SiteAnswer:
        try:
            return await asyncio.to_thread(self._lookup, site, q)
        except Exception as e:  # noqa: BLE001 - any failure of an outside site is "site down", never a crash
            log.warning("lyrics site %s failed for %s: %r", site, q.titles[:1], e)
            return SiteDown()

    def _lookup(self, site: LyricsSite, q: SongQuery) -> SiteAnswer:
        title = core_title(q.titles[0]) if q.titles else ""
        artist = q.artists[0] if q.artists else ""
        enc = urllib.parse.quote
        match site:
            case "lrclib":
                hits = json.loads(self._fetch(f"https://lrclib.net/api/search?track_name={enc(title)}&artist_name={enc(artist)}"))
                text = parse_lrclib(hits, q)
                if text is None:
                    text = parse_lrclib(json.loads(self._fetch(f"https://lrclib.net/api/search?q={enc(title + ' ' + artist)}")), q)
                return self._text(text, None, q)
            case "genius":
                url = parse_genius_search(json.loads(self._fetch(f"https://genius.com/api/search/multi?q={enc(title + ' ' + artist)}")), q)
                return SiteNone() if url is None else self._text(parse_genius_page(self._fetch(url)), url, q)
            case "utanet":
                try:  # sort=4: most popular first, so the well-known song of a common title is on the first page
                    found = self._fetch(f"https://www.uta-net.com/search/?Keyword={enc(title)}&Aselect=2&Bselect=3&sort=4")
                except urllib.error.HTTPError as e:
                    if e.code == 404:  # Uta-Net answers a search with no results with 404
                        return SiteNone()
                    raise
                url = parse_utanet_search(found, q)
                return SiteNone() if url is None else self._text(parse_utanet_song(self._fetch(url)), url, q)
            case "kkbox":
                # The search page is the only KKBOX page the app reads, and KKBOX may answer it with its bot check
                # too. The phone's own browser passes that check, so the answer is always a link: the song's page
                # when the top result is this song, else the search results.
                try:
                    url = parse_kkbox_search(self._fetch(f"https://www.kkbox.com/tw/tc/search?q={enc(title)}"), q)
                except Exception as e:  # noqa: BLE001
                    log.info("KKBOX search unreadable (%r); linking to its search page", e)
                    url = None
                return SiteLink(url, found=True) if url else SiteLink(kkbox_search_url(q), found=False)

    @staticmethod
    def _text(text: str | None, url: str | None, q: SongQuery) -> SiteAnswer:
        if text is None or not text.strip():
            return SiteNone()
        return SiteText(tidy(text, q.language), url)


# ---- the service the HTTP route uses ----

@dataclass(frozen=True, slots=True)
class _Kept:
    answer: SiteAnswer
    at: float


class SiteLyrics:
    """Answers per library song and site, kept for CACHE_S. One lookup runs per song and site at a time, so many
    phones opening the same song make one request to the site."""

    def __init__(self, library: Library, sites: LyricsSites, clock: Callable[[], float] = time.monotonic) -> None:
        self._library = library
        self._sites = sites
        self._clock = clock
        self._kept: dict[tuple[SongId, LyricsSite], _Kept] = {}
        self._locks: dict[tuple[SongId, LyricsSite], asyncio.Lock] = {}

    def query(self, song: SongId) -> SongQuery | None:
        rec = self._library.get(song)
        if rec is None:
            return None
        titles = tuple(dict.fromkeys((rec.meta.title, *rec.alt_titles)))
        artists = tuple(dict.fromkeys((rec.meta.artist.name, *rec.artist_names)))
        return SongQuery(titles, artists, language_of(rec.language, rec.meta.title))

    def sites(self, song: SongId) -> tuple[LyricsSite, ...] | None:
        q = self.query(song)
        return None if q is None else site_order(q.language)

    async def lookup(self, song: SongId, site: LyricsSite) -> SiteAnswer | None:
        """None if the song is not in the library."""
        q = self.query(song)
        if q is None:
            return None
        key = (song, site)
        async with self._locks.setdefault(key, asyncio.Lock()):
            kept = self._kept.get(key)
            if kept is not None and self._clock() - kept.at < CACHE_S:
                return kept.answer
            answer = await self._sites.lookup(site, q)
            if not isinstance(answer, SiteDown):
                self._kept[key] = _Kept(answer, self._clock())
            return answer


__all__ = [
    "ALL_SITES", "LyricsSites", "SiteAnswer", "SiteDown", "SiteLink", "SiteLyrics", "SiteNone", "SiteText",
    "SongQuery", "WebLyricsSites", "site_order",
]
