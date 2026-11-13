import asyncio
from pathlib import Path

import pytest

from karaoke.core import ArtistId, ArtistRef, SongId, SongMeta
from karaoke.songs.catalog import (
    Catalog, ChooseVideo, OfficialVideo, OnlineUnavailable, UnknownOnlineKey, core_title, display_language,
    is_official_video,
)
from karaoke.songs.library import Library, SongRecord

EASON = "UC2rCynaFhWz7MeRoqJLvcow"
AVRIL = "UCavril"


def song(vid: str, title: str, artist: str, artist_id: str, seconds: int = 250) -> dict:
    return {"resultType": "song", "videoId": vid, "title": title, "duration_seconds": seconds,
            "artists": [{"name": artist, "id": artist_id}], "thumbnails": [{"url": f"t/{vid}", "width": 60}]}


def video(vid: str, title: str, artist_id: str, kind: str = "MUSIC_VIDEO_TYPE_OMV") -> dict:
    return {"resultType": "video", "videoId": vid, "title": title, "videoType": kind, "duration": "4:30",
            "artists": [{"name": "x", "id": artist_id}]}


class FakeYT:
    def __init__(self) -> None:
        self.zh = [song("atv1", "陀飛輪", "陳奕迅", EASON), song("atv2", "超複雜", "艾薇兒", AVRIL),
                   {"resultType": "artist", "browseId": EASON}]
        self.en = [song("atv1", "陀飛輪", "Eason Chan", EASON), song("atv2", "Complicated", "Avril Lavigne", AVRIL)]
        self.vids: list[dict] = []
        self.fail = False
        self.video_queries: list[str] = []

    def search(self, query: str, language: str) -> list[dict]:
        if self.fail:
            raise ConnectionError("down")
        return self.zh if language == "zh_TW" else self.en

    def videos(self, query: str) -> list[dict]:
        self.video_queries.append(query)
        return self.vids

    def artist(self, artist: ArtistId, language: str) -> dict:
        return {"name": "陳奕迅" if language == "zh_TW" else "Eason Chan",
                "songs": {"results": [s for s in (self.zh if language == "zh_TW" else self.en)
                                      if s.get("resultType") == "song"]}}


@pytest.fixture
def library(tmp_path: Path) -> Library:
    lib = Library(tmp_path / "lib")
    lib.open()
    return lib


def test_display_title_rule() -> None:
    assert display_language("超複雜", "Complicated") == "en"
    assert display_language("陀飛輪", "陀飛輪") == "zh_TW"
    assert display_language("Lemon Tree", "Lemon Tree") == "zh_TW"
    assert display_language("超複雜", None) == "zh_TW"


def test_core_title_drops_edition_tags() -> None:
    assert core_title("陀飛輪 (Live)") == "陀飛輪"
    assert core_title("AIR (Day Version)") == "AIR"
    assert core_title("Sugar - Remastered") == "Sugar"
    assert core_title("K歌之王【粵】") == "K歌之王"


def test_strict_official_video_rule_needs_all_three() -> None:
    cores = ("陀飛輪",)
    assert is_official_video(video("v", "陳奕迅 Eason Chan - 陀飛輪 (Official Music Video)", EASON), cores, ArtistId(EASON))
    assert not is_official_video(video("v", "陀飛輪 piano cover", "UCother"), cores, ArtistId(EASON))
    assert not is_official_video(video("v", "陀飛輪 lyric video", EASON, "MUSIC_VIDEO_TYPE_UGC"), cores, ArtistId(EASON))
    assert not is_official_video(video("v", "陳奕迅 - 富士山下", EASON), cores, ArtistId(EASON))
    assert is_official_video(video("v", "陈奕迅 - 陀飞轮 MV", EASON), cores, ArtistId(EASON))


def test_search_pairs_languages_and_applies_the_display_rule(library: Library) -> None:
    result = asyncio.run(Catalog(library, FakeYT()).search("x"))
    assert not isinstance(result.online, OnlineUnavailable)
    shown = [(s.title, s.artist.name, s.artist.id) for s in result.online]
    assert shown == [("陀飛輪", "陳奕迅", EASON), ("Complicated", "Avril Lavigne", AVRIL)]


def test_search_failure_still_returns_library_hits(library: Library) -> None:
    yt = FakeYT()
    yt.fail = True
    result = asyncio.run(Catalog(library, yt).search("x"))
    assert isinstance(result.online, OnlineUnavailable)


def test_results_without_any_song_mean_the_format_changed(library: Library) -> None:
    yt = FakeYT()
    yt.zh = [{"resultType": "song", "title": "no video id"}]
    yt.en = []
    assert isinstance(asyncio.run(Catalog(library, yt).search("x")).online, OnlineUnavailable)


def test_official_video_is_picked_and_resolves_to_its_video_id(library: Library) -> None:
    yt = FakeYT()
    yt.vids = [video("cover", "陀飛輪 cover", "UCother"), video("omv", "陳奕迅 Eason Chan - 陀飛輪 MV", EASON)]
    cat = Catalog(library, yt)
    key = asyncio.run(cat.search("x")).online[0].key  # type: ignore[union-attr]
    res = asyncio.run(cat.resolve_video(key))
    assert isinstance(res, OfficialVideo)
    meta = cat.pick(res.pick)
    assert meta == SongMeta(SongId("omv"), "陀飛輪", ArtistRef(ArtistId(EASON), "陳奕迅"), 270.0)
    assert yt.video_queries == ["陳奕迅 陀飛輪"]
    names = asyncio.run(cat.describe(meta))
    assert set(names.artist_names) == {"陳奕迅", "Eason Chan"}


def test_no_official_video_offers_candidates_each_with_its_own_pick(library: Library) -> None:
    yt = FakeYT()
    yt.vids = [video(f"v{i}", f"陀飛輪 {i}", "UCother") for i in range(9)]
    cat = Catalog(library, yt)
    key = asyncio.run(cat.search("x")).online[0].key  # type: ignore[union-attr]
    res = asyncio.run(cat.resolve_video(key))
    assert isinstance(res, ChooseVideo) and len(res.candidates) == 6
    picked = cat.pick(res.candidates[2].pick)
    assert picked and picked.id == "v2" and picked.title == "陀飛輪"
    assert cat.pick("forged") is None  # type: ignore[arg-type]


def test_video_options_put_the_official_video_first_and_still_offer_others(library: Library) -> None:
    """Spec "Choose the video": the phone always shows a list, the best guess first and marked."""
    yt = FakeYT()
    yt.vids = [video("cover", "陀飛輪 cover", "UCother"), video("omv", "陳奕迅 Eason Chan - 陀飛輪 MV", EASON),
               video("cover", "duplicate", "UCother"), *(video(f"v{i}", f"陀飛輪 {i}", "UCother") for i in range(9))]
    cat = Catalog(library, yt)
    key = asyncio.run(cat.search("x")).online[0].key  # type: ignore[union-attr]
    options = asyncio.run(cat.video_options(key))
    assert [o.video_id for o in options] == ["omv", "cover", "v0", "v1", "v2", "v3"]
    assert [o.official for o in options] == [True, False, False, False, False, False]
    picked = cat.pick(options[1].pick)
    assert picked == SongMeta(SongId("cover"), "陀飛輪", ArtistRef(ArtistId(EASON), "陳奕迅"), 270.0)


def test_video_options_for_a_library_song_leave_out_its_current_video(library: Library) -> None:
    meta = SongMeta(SongId("omv"), "陀飛輪", ArtistRef(ArtistId(EASON), "陳奕迅"), 250)
    d = library.staging_dir(meta.id)
    for f in ("video.mp4", "instrumental.opus", "vocals.opus", "lyrics.json"):
        (d / f).write_bytes(b"x")
    library.install(meta.id, SongRecord(meta, ("陳奕迅",), ("陀飛輪",), "zh", "lrclib", ""))
    yt = FakeYT()
    yt.vids = [video("omv", "陳奕迅 - 陀飛輪 MV", EASON), video("live", "陀飛輪 live", "UCother")]
    cat = Catalog(library, yt)
    options = asyncio.run(cat.video_options("lib:omv"))  # type: ignore[arg-type]
    assert [o.video_id for o in options] == ["live"]
    assert cat.pick(options[0].pick) == SongMeta(SongId("live"), "陀飛輪", meta.artist, 270.0)
    with pytest.raises(UnknownOnlineKey):
        asyncio.run(cat.video_options("lib:missing"))  # type: ignore[arg-type]


def test_unknown_key_raises(library: Library) -> None:
    with pytest.raises(UnknownOnlineKey):
        asyncio.run(Catalog(library, FakeYT()).resolve_video("nope"))  # type: ignore[arg-type]


def test_online_duplicates_of_library_songs_are_dropped(library: Library, tmp_path: Path) -> None:
    meta = SongMeta(SongId("omv1"), "陀飛輪", ArtistRef(ArtistId(EASON), "陳奕迅"), 250)
    d = library.staging_dir(meta.id)
    for f in ("video.mp4", "instrumental.opus", "vocals.opus", "lyrics.json"):
        (d / f).write_bytes(b"x")
    library.install(meta.id, SongRecord(meta, ("陳奕迅", "Eason Chan"), ("陀飛輪",), "zh", "lrclib", ""))
    result = asyncio.run(Catalog(library, FakeYT()).search("陀飛輪"))
    assert [h.song.id for h in result.library] == ["omv1"]
    assert [s.title for s in result.online] == ["Complicated"]  # type: ignore[union-attr]


class TrackYT(FakeYT):
    def __init__(self, kind: str) -> None:
        super().__init__()
        self.kind = kind

    def track(self, video_id: SongId, language: str) -> dict | None:
        name, title = ("陳奕迅", "陀飛輪") if language == "zh_TW" else ("Eason Chan", "陀飛輪")
        return {"videoId": video_id, "title": title, "videoType": self.kind, "length": "4:48",
                "artists": [{"name": name, "id": EASON}], "thumbnail": [{"url": "t", "width": 60}]}


def test_identify_trusts_an_official_videos_own_record(library: Library) -> None:
    cat = Catalog(library, TrackYT("MUSIC_VIDEO_TYPE_OMV"))
    key = asyncio.run(cat.identify(SongId("omv1")))
    assert key == "omv1"
    yt = cat._yt
    assert isinstance(yt, TrackYT)
    yt.vids = [video("omv1", "陀飛輪", EASON)]
    resolved = asyncio.run(cat.resolve_video(key))
    assert isinstance(resolved, OfficialVideo)
    meta = cat.pick(resolved.pick)
    assert meta is not None and (meta.title, meta.artist.name, meta.id) == ("陀飛輪", "陳奕迅", "omv1")


def test_identify_ignores_fan_uploads_whose_record_names_the_uploader(library: Library) -> None:
    assert asyncio.run(Catalog(library, TrackYT("MUSIC_VIDEO_TYPE_UGC")).identify(SongId("ugc1"))) is None
