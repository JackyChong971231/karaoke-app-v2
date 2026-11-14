"""Lyrics sites (spec "Read the lyrics from a lyrics site"). The page samples copy the shape each site returned
when probed on 2026-11-14, cut down to the parts the parsers read, with made-up lyrics."""

from __future__ import annotations

import asyncio
import json
import urllib.error
from email.message import Message
from pathlib import Path

import pytest

from karaoke.core import ArtistId, ArtistRef, SongId, SongMeta
from karaoke.songs.library import Library, SongRecord
from karaoke.songs.lyric_sites import (
    SiteDown, SiteLink, SiteLyrics, SiteNone, SiteText, SongQuery, WebLyricsSites, parse_genius_page,
    parse_genius_search, parse_kkbox_search, parse_lrclib, parse_utanet_search, parse_utanet_song, site_order, tidy,
)
from karaoke.vocab import LyricsSite

EASON = SongQuery(("陀飛輪",), ("陳奕迅", "Eason Chan"), "zh")
ADELE = SongQuery(("Someone Like You",), ("Adele",), "en")
LEMON = SongQuery(("Lemon",), ("米津玄師", "Kenshi Yonezu"), "ja")


def test_the_song_languages_own_site_comes_first_and_every_site_is_offered() -> None:
    assert site_order("zh") == ("kkbox", "lrclib", "utanet", "genius")
    assert site_order("ja") == ("utanet", "kkbox", "lrclib", "genius")
    assert site_order("en") == ("genius", "kkbox", "lrclib", "utanet")
    assert site_order("ko") == ("lrclib", "kkbox", "utanet", "genius")


def test_tidy_collapses_blank_runs_drops_odd_spaces_and_shows_chinese_in_traditional() -> None:
    raw = "\n\n过去十八岁 没戴表​\n\n\n\n不过有时间　 \n\n"
    assert tidy(raw, "zh") == "過去十八歲 沒戴錶\n\n不過有時間"
    assert tidy("夢なら　ば", "ja") == "夢なら ば"


# ---- LRCLIB ----

def test_lrclib_takes_plain_lyrics_of_the_same_song_by_the_same_singer() -> None:
    hits = [
        {"trackName": "陀飛輪", "artistName": "Cover Singer", "plainLyrics": "wrong singer"},
        {"trackName": "陀飛輪 (Live)", "artistName": "陳奕迅", "instrumental": False,
         "plainLyrics": "line one\nline two", "syncedLyrics": "[00:01.00] line one"},
    ]
    assert parse_lrclib(hits, EASON) == "line one\nline two"


def test_lrclib_strips_times_from_synced_only_lyrics_and_finds_nothing_for_another_singer() -> None:
    synced = [{"trackName": "Someone Like You", "artistName": "Adele", "syncedLyrics": "[00:01.00] a\n[00:02.50]b"}]
    assert parse_lrclib(synced, ADELE) == " a\nb"
    other = [{"trackName": "Someone Like You", "artistName": "Somebody Else", "plainLyrics": "x"}]
    assert parse_lrclib(other, ADELE) is None


# ---- Genius ----

def genius_search(*songs: tuple[str, str, str]) -> dict:  # type: ignore[type-arg]
    hits = [{"type": "song", "result": {"title": t, "url": u, "primary_artist": {"name": a}}} for t, a, u in songs]
    return {"response": {"sections": [{"type": "top_hit", "hits": hits[:1]}, {"type": "song", "hits": hits}]}}


def test_genius_picks_the_song_by_the_same_singer_never_a_translation_or_a_cover() -> None:
    data = genius_search(
        ("Someone Like You", "Genius English Translations", "https://genius.com/translation"),
        ("Someone Like You (Adele Cover)", "Lukas Nelson", "https://genius.com/cover"),
        ("Someone Like You", "Adele", "https://genius.com/Adele-someone-like-you-lyrics"),
    )
    assert parse_genius_search(data, ADELE) == "https://genius.com/Adele-someone-like-you-lyrics"
    assert parse_genius_search(genius_search(("Someone Like You", "Lukas Nelson", "u")), ADELE) is None


def test_genius_reads_every_lyrics_block_and_skips_the_header_and_ads() -> None:
    page = (
        '<html><body><div data-lyrics-container="true" class="Lyrics__Container">'
        '<div data-exclude-from-selection="true" class="LyricsHeader"><button><span>12 Contributors</span></button>'
        '<div>Someone Like You Lyrics</div></div>'
        '[Verse 1]<br/>I heard <i>that</i> you&#x27;re settled down<br>That you found a girl</div>'
        '<div data-exclude-from-selection="true"><div id="div-gpt-ad"></div><img src="ad.png"></div>'
        '<div data-lyrics-container="true" class="Lyrics__Container">[Chorus]<br/>Never mind</div>'
        '<div class="footer">Embed</div></body></html>'
    )
    assert parse_genius_page(page) == "[Verse 1]\nI heard that you're settled down\nThat you found a girl\n[Chorus]\nNever mind"


def test_a_genius_page_without_a_lyrics_block_is_an_unknown_shape() -> None:
    with pytest.raises(ValueError):
        parse_genius_page("<html><body>We changed our page</body></html>")


# ---- Uta-Net ----

def utanet_row(n: int, title: str, singer: str) -> str:
    return (f'<tr><td class="sp-w-100 pt-0 pt-lg-2"><a href="/song/{n}/" class="py-2 py-lg-0">'
            f'<span class="fw-bold songlist-title">{title}</span><span class="d-inline d-lg-none ps-1 icon-new"></span>'
            f'<span class="d-block d-lg-none utaidashi">{singer}</span></a></td>'
            f'<td class="sp-none fw-bold"><a href="/artist/1/">{singer}</a></td></tr>')


def test_utanet_picks_the_row_with_the_same_title_and_singer() -> None:
    page = utanet_row(303324, "青いレモンの季節", "NMB48") + utanet_row(244127, "Lemon", "米津玄師") + utanet_row(1, "Lemon", "Other")
    assert parse_utanet_search(page, LEMON) == "https://www.uta-net.com/song/244127/"
    assert parse_utanet_search(utanet_row(1, "Lemon", "Other"), LEMON) is None


def test_utanet_song_page_text_keeps_its_line_breaks() -> None:
    page = '<div id="kashi_area" itemprop="text">夢ならば<br />どれほど&amp;<br /><br />よかった</div><div>other</div>'
    assert parse_utanet_song(page) == "夢ならば\nどれほど&\n\nよかった"
    with pytest.raises(ValueError):
        parse_utanet_song("<html>no lyrics here</html>")


# ---- KKBOX ----

def kkbox_page(top: str) -> str:
    return (f'<main><div class="container"><div class="top-result">{top}</div></div>'
            '<div class="single-type mix-song"><h2>歌曲</h2><div class="song-ul"></div></div></main>')


def kkbox_song(title: str, singer: str, song_id: str) -> str:
    return (f'<h1>最佳結果 - 歌曲</h1><div class="content"><song-li data-id="{song_id}" data-lyrics="true">'
            f'<img slot="album-cover" src="x.jpg" alt="{title}">'
            f'<a slot="song-name"\n    title="{title}"\n    href="https://www.kkbox.com/tw/tc/song/{song_id}"><mark-text>{title}</mark-text></a>'
            f'<a slot="artist-name" href="https://www.kkbox.com/tw/tc/artist/A1" title="{singer}">{singer}</a>'
            '</song-li></div>')


def test_kkbox_links_the_top_result_only_when_it_is_this_song_by_this_singer() -> None:
    assert parse_kkbox_search(kkbox_page(kkbox_song("陀飛輪", "陳奕迅 (Eason Chan)", "GrT71")), EASON) == \
        "https://www.kkbox.com/tw/tc/song/GrT71"
    assert parse_kkbox_search(kkbox_page(kkbox_song("陀飛輪", "MC 張天賦", "Other")), EASON) is None
    singer_on_top = '<h1>最佳結果 - 歌手</h1><div class="content"><artist-card data-id="A1"></artist-card></div>'
    assert parse_kkbox_search(kkbox_page(singer_on_top), EASON) is None


# ---- the real reader, with the network replaced ----

def fetcher(pages: dict[str, str | Exception]):  # type: ignore[no-untyped-def]
    def fetch(url: str) -> str:
        for prefix, page in pages.items():
            if url.startswith(prefix):
                if isinstance(page, Exception):
                    raise page
                return page
        raise AssertionError(f"unexpected fetch {url}")
    return fetch


def lookup(site: LyricsSite, q: SongQuery, pages: dict[str, str | Exception]):  # type: ignore[no-untyped-def]
    return asyncio.run(WebLyricsSites(fetcher(pages)).lookup(site, q))


def test_kkbox_is_always_a_link_even_when_its_search_answers_with_a_bot_check() -> None:
    found = lookup("kkbox", EASON, {"https://www.kkbox.com/tw/tc/search": kkbox_page(kkbox_song("陀飛輪", "陳奕迅", "GrT71"))})
    assert found == SiteLink("https://www.kkbox.com/tw/tc/song/GrT71", found=True)
    blocked = urllib.error.HTTPError("u", 202, "challenge", Message(), None)
    fallback = lookup("kkbox", EASON, {"https://www.kkbox.com/tw/tc/search": blocked})
    assert fallback == SiteLink(
        "https://www.kkbox.com/tw/tc/search?q=%E9%99%80%E9%A3%9B%E8%BC%AA%20%E9%99%B3%E5%A5%95%E8%BF%85", found=False)


def test_a_site_that_fails_or_changes_shape_is_down_and_utanets_404_means_no_results() -> None:
    assert lookup("genius", ADELE, {"https://genius.com/": TimeoutError()}) == SiteDown()
    assert lookup("lrclib", ADELE, {"https://lrclib.net/": "{\"not\": \"a list\"}"}) == SiteDown()
    no_results = urllib.error.HTTPError("u", 404, "Not Found", Message(), None)
    assert lookup("utanet", LEMON, {"https://www.uta-net.com/search/": no_results}) == SiteNone()


def test_genius_text_comes_with_its_page_and_lrclib_text_without_one() -> None:
    page = '<div data-lyrics-container="true">I heard<br>that you</div>'
    got = lookup("genius", ADELE, {
        "https://genius.com/api/search/multi": json.dumps(genius_search(("Someone Like You", "Adele", "https://genius.com/a"))),
        "https://genius.com/a": page,
    })
    assert got == SiteText("I heard\nthat you", "https://genius.com/a")
    lrc = json.dumps([{"trackName": "陀飛輪", "artistName": "陳奕迅", "plainLyrics": "过去十八岁"}])
    assert lookup("lrclib", EASON, {"https://lrclib.net/": lrc}) == SiteText("過去十八歲", None)


# ---- per library song, kept for a while ----

class CountingSites:
    def __init__(self, answers: list[SiteText | SiteDown]) -> None:
        self.answers = answers
        self.asked: list[tuple[LyricsSite, SongQuery]] = []

    async def lookup(self, site: LyricsSite, q: SongQuery) -> SiteText | SiteDown:
        self.asked.append((site, q))
        await asyncio.sleep(0.01)
        return self.answers.pop(0)


def library_with(tmp_path: Path) -> Library:
    library = Library(tmp_path / "lib")
    library.open()
    song = SongId("vidsite0001")
    d = library.staging_dir(song)
    for f in ("video.mp4", "instrumental.opus", "vocals.opus", "lyrics.json"):
        (d / f).write_bytes(b"x")
    meta = SongMeta(song, "陀飛輪 (Live)", ArtistRef(ArtistId("UCeason"), "陳奕迅"), 10.0)
    library.install(song, SongRecord(meta, ("陳奕迅", "Eason Chan"), ("Tourbillon",), "zh", "lrclib", ""))
    return library


def test_many_phones_asking_at_once_make_one_request_and_a_down_site_is_asked_again(tmp_path: Path) -> None:
    sites = CountingSites([SiteDown(), SiteText("a", None)])
    now = [0.0]
    service = SiteLyrics(library_with(tmp_path), sites, clock=lambda: now[0])
    song = SongId("vidsite0001")

    async def run() -> None:
        assert await service.lookup(song, "genius") == SiteDown()
        answers = await asyncio.gather(*(service.lookup(song, "genius") for _ in range(5)))
        assert answers == [SiteText("a", None)] * 5

    asyncio.run(run())
    assert len(sites.asked) == 2
    site, q = sites.asked[0]
    assert q == SongQuery(("陀飛輪 (Live)", "Tourbillon"), ("陳奕迅", "Eason Chan"), "zh")
    assert service.sites(song) == site_order("zh")
    assert service.sites(SongId("notinlibrary")) is None
    assert asyncio.run(service.lookup(SongId("notinlibrary"), "genius")) is None
