"""Spec "Browse for songs": place boxes of 熱門 shelves, singers placed by the shelves they appear on, the user's
choice winning, and chart songs from elsewhere dropped."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from karaoke.core import ArtistId, ArtistRef, SongId, SongMeta
from karaoke.harness.fakes import FakeYouTubeMusic
from karaoke.songs.browse import ArtistPlaces, Browse, pick_playlist
from karaoke.songs.catalog import Catalog, LibraryHit, OnlineSong
from karaoke.songs.library import Library, SongRecord


def install(library: Library, meta: SongMeta) -> None:
    d = library.staging_dir(meta.id)
    for f in ("video.mp4", "instrumental.opus", "vocals.opus", "lyrics.json"):
        (d / f).write_bytes(b"x")
    library.install(meta.id, SongRecord(meta, (meta.artist.name,), (meta.title,), "zh", "lrclib", ""))


def world(tmp_path: Path, yt: Any = None) -> tuple[Browse, Library]:
    library = Library(tmp_path / "lib")
    library.open()
    install(library, SongMeta(SongId("fklib000002"), "河流", ArtistRef(ArtistId("UCfakeLibSinger"), "圖書館歌手"), 10))
    places = ArtistPlaces(tmp_path / "artist-places.json")
    places.load()
    yt = yt or FakeYouTubeMusic()
    return Browse(Catalog(library, yt), library, yt, places), library


def titles(items: tuple[LibraryHit | OnlineSong, ...]) -> list[str]:
    return [i.song.title if isinstance(i, LibraryHit) else i.title for i in items]


def test_hong_kong_box_shows_its_hits_drops_kpop_and_places_its_singers(tmp_path: Path) -> None:
    browse, _ = world(tmp_path)
    page = asyncio.run(browse.page("hk"))
    assert [s.title for s in page.shelves] == ["HK 熱門 Top 100", "最新熱門廣東歌"]
    chart = page.shelves[0].items
    assert titles(chart) == ["測試之歌", "河流"], "NEON by a K-pop act is dropped; titles are cleaned"
    assert isinstance(chart[1], LibraryHit), "a chart song already in the library is shown as ready"
    assert isinstance(chart[0], OnlineSong) and chart[0].artist.name == "測試歌手"
    assert {s.artist.name for s in page.singers} == {"測試歌手", "圖書館歌手"}
    assert [h.song.title for h in page.library] == ["河流"], "library songs whose singer is from Hong Kong"
    assert page.online_ok


def test_the_users_choice_wins_over_the_shelf_guess(tmp_path: Path) -> None:
    browse, _ = world(tmp_path)
    asyncio.run(browse.page("hk"))
    singer = ArtistRef(ArtistId("UCfakeArtistB"), "測試歌手")
    assert browse.places.place_of(singer.id) == "hk"
    browse.places.choose(singer, "tw")
    assert browse.places.place_of(singer.id) == "tw" and browse.places.chosen(singer.id)
    again = ArtistPlaces(tmp_path / "artist-places.json")
    again.load()
    assert again.place_of(singer.id) == "tw", "the choice is saved"
    browse.places.choose(singer, None)
    assert browse.places.place_of(singer.id) == "hk"


def test_a_singer_on_two_places_belongs_where_seen_most_with_cantonese_lists_counting_double(tmp_path: Path) -> None:
    places = ArtistPlaces(tmp_path / "artist-places.json")
    gem = ArtistId("UCcross")
    places.recount("tw", {gem: ("Cross Singer", 3.0)})
    places.recount("hk", {gem: ("Cross Singer", 1.0 + 2.0 * 1)})
    assert places.place_of(gem) == "tw"
    places.recount("hk", {gem: ("Cross Singer", 1.0 + 2.0 * 2)})
    assert places.place_of(gem) == "hk"


def test_known_singers_are_placed_by_name_before_the_shelf_count(tmp_path: Path) -> None:
    """G.E.M. appears on more 台灣 shelves than 香港 ones, so counting alone puts her under 台灣."""
    places = ArtistPlaces(tmp_path / "artist-places.json")
    gem = ArtistId("UCBRh2Z_U1Lw9-YJ-XGZ8M2Q")
    places.recount("tw", {gem: ("G.E.M.", 3.0)})
    places.recount("hk", {gem: ("G.E.M.", 1.0)})
    assert places.place_of(gem) == "hk"
    places.choose(ArtistRef(gem, "G.E.M."), "cn")
    assert places.place_of(gem) == "cn", "the user's choice still wins"


def test_shelves_are_cached_and_a_place_with_nothing_online_still_answers(tmp_path: Path) -> None:
    class Counting(FakeYouTubeMusic):
        calls = 0

        def charts(self, country: str) -> dict[str, Any]:
            Counting.calls += 1
            return super().charts(country)

    browse, _ = world(tmp_path, Counting())
    asyncio.run(browse.page("hk"))
    asyncio.run(browse.page("hk"))
    assert Counting.calls == 1
    empty = asyncio.run(browse.page("cn"))
    assert empty.shelves == () and not empty.online_ok


def test_label_playlists_are_preferred_over_fan_lists() -> None:
    results = [{"title": "fan mix", "author": "Someone", "browseId": "VL1"},
               {"title": "最新熱門廣東歌", "author": "warnermusichk", "browseId": "VL2"}]
    assert pick_playlist(results) == results[1]
    assert pick_playlist([results[0]]) == results[0]
    assert pick_playlist([]) is None
    dated = [{"title": "2018 KKBOX Taiwanese POP", "author": "KKBOX", "browseId": "VL3"},
             {"title": "華語新歌 2026", "author": "fan", "browseId": "VL4"}]
    assert pick_playlist(dated, ("kkbox",), "2026") == dated[1], "this year's hits beat an old label list"


def test_a_song_by_a_singer_known_to_be_from_elsewhere_leaves_the_box(tmp_path: Path) -> None:
    browse, _ = world(tmp_path)
    assert "測試之歌" in titles(asyncio.run(browse.page("hk")).shelves[0].items)
    browse.places.choose(ArtistRef(ArtistId("UCfakeArtistB"), "測試歌手"), "tw")
    assert "測試之歌" not in titles(asyncio.run(browse.page("hk")).shelves[0].items)
