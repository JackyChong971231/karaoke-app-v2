import asyncio
import json
from pathlib import Path

import pytest

from karaoke.core import ArtistId, SongId
from karaoke.importer import ImportService, V1Source, clean_title, video_id_from_url
from karaoke.songs.catalog import Catalog, ChooseVideo
from karaoke.songs.library import Library
from karaoke.songs.prepare import FromV1Files, FromYouTube, PrepRequest

EASON = "UCeason"


def song(vid: str, title: str, artist: str) -> dict:
    return {"resultType": "song", "videoId": vid, "title": title, "duration_seconds": 240,
            "artists": [{"name": artist, "id": EASON}]}


class FakeYT:
    def search(self, query: str, language: str) -> list[dict]:
        if "陀飛輪" in query:
            return [song("atv1", "陀飛輪", "陳奕迅")]
        if "K歌之王" in query:
            return [song("atv2", "K歌之王", "陳奕迅")]
        return []

    def videos(self, query: str) -> list[dict]:
        if "陀飛輪" in query:
            return [{"videoId": "omvtourbill", "title": "陳奕迅 - 陀飛輪 (Official MV)", "videoType": "MUSIC_VIDEO_TYPE_OMV",
                     "artists": [{"name": "陳奕迅", "id": EASON}]}]
        return [{"videoId": "someupload1", "title": "K歌之王 cover", "videoType": "MUSIC_VIDEO_TYPE_UGC", "artists": []}]

    def artist(self, artist: ArtistId, language: str) -> dict:
        return {}


class RecordingPreparer:
    def __init__(self) -> None:
        self.demand: dict[str, list[PrepRequest]] = {}

    def set_demand(self, lane: str, wanted: list[PrepRequest]) -> None:
        self.demand[lane] = list(wanted)


def make_v1(root: Path) -> Path:
    data = root / "karaoke_data"
    folders = {
        "universalmusichk_陳奕迅 - 陀飛輪 (Official Music Video)": ("陳奕迅 - 陀飛輪 (Official Music Video)", "https://youtu.be/v1tourbilla?si=x", 9),
        "英皇娛樂 eeg music_陳奕迅 Eason Chan《K歌之王》[Official MV]": ("陳奕迅 Eason Chan《K歌之王》[Official MV]", "https://music.youtube.com/watch?v=v1kgezhiwan&si=y", 14),
        "Someone_Unknown song": (None, None, 3),
        "Broken_Half copied": ("Half copied", "https://youtu.be/halfcopied1", 20),
    }
    counts = {}
    for name, (title, url, plays) in folders.items():
        d = data / name
        d.mkdir(parents=True)
        if title:
            (d / "meta.json").write_text(json.dumps({"title": title, "artist": "x", "url": url}), "utf-8")
        files = ("video.mp4",) if name.startswith("Broken") else ("video.mp4", "instrumental.wav", "vocals.wav")
        for f in files:
            (d / f).write_bytes(b"x")
        counts[title or name.split("_", 1)[1]] = plays
    (root / "Karaoke_state.json").write_text(json.dumps({"queue": [], "song_counts": counts}), "utf-8")
    return root


def snapshot(root: Path) -> dict[str, tuple[int, float]]:
    return {str(p): (p.stat().st_size, p.stat().st_mtime) for p in root.rglob("*")}


@pytest.fixture
def setup(tmp_path: Path) -> tuple[ImportService, Path, RecordingPreparer, Library, Catalog]:
    v1 = make_v1(tmp_path / "v1")
    lib = Library(tmp_path / "lib")
    lib.open()
    cat = Catalog(lib, FakeYT())
    prep = RecordingPreparer()
    svc = ImportService(V1Source(v1), tmp_path / "import-plan.json", cat, lib, prep)  # type: ignore[arg-type]
    return svc, v1, prep, lib, cat


def test_video_ids_come_from_every_v1_url_shape() -> None:
    assert video_id_from_url("https://youtu.be/O-n5jby8htA?si=nKp7Q0bdSib-AyJl") == "O-n5jby8htA"
    assert video_id_from_url("https://music.youtube.com/watch?v=MCEcWcIww5k&si=Aw8") == "MCEcWcIww5k"
    assert video_id_from_url("") is None


def test_clean_title_strips_video_noise() -> None:
    assert clean_title("陳奕迅 Eason Chan《K歌之王》[Official MV]") == "陳奕迅 Eason Chan《K歌之王》"
    assert clean_title("陳僖儀 - 蜚蜚『其實有多精彩』【動態歌詞Lyrics】") == "陳僖儀 - 蜚蜚"
    assert clean_title("Fools Garden - Lemon Tree (Official HD Video)") == "Fools Garden - Lemon Tree"


def test_v1_songs_are_ordered_by_play_count(setup) -> None:  # type: ignore[no-untyped-def]
    svc, v1, *_ = setup
    songs = V1Source(v1).songs_by_play_count()
    assert [(s.raw_title, s.play_count, s.video_id) for s in songs] == [
        ("Half copied", 20, "halfcopied1"),
        ("陳奕迅 Eason Chan《K歌之王》[Official MV]", 14, "v1kgezhiwan"),
        ("陳奕迅 - 陀飛輪 (Official Music Video)", 9, "v1tourbilla"),
        ("Unknown song", 3, None),
    ]


def test_plan_proposes_official_video_or_v1_video_and_persists(setup, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    svc, v1, prep, lib, cat = setup
    before = snapshot(v1)
    asyncio.run(svc.plan(3))
    items = {i.v1.raw_title: i for i in svc.items()}
    assert list(items) == ["Half copied", "陳奕迅 Eason Chan《K歌之王》[Official MV]", "陳奕迅 - 陀飛輪 (Official Music Video)"]
    assert items["Half copied"].decision == "skipped" and "instrumental.wav" in (items["Half copied"].note or "")
    kge = items["陳奕迅 Eason Chan《K歌之王》[Official MV]"]
    assert kge.proposed and kge.proposed.id == "v1kgezhiwan" and kge.proposed.title == "K歌之王" and kge.reuse_v1_video
    tour = items["陳奕迅 - 陀飛輪 (Official Music Video)"]
    assert tour.proposed and tour.proposed.id == "omvtourbill" and not tour.reuse_v1_video

    asyncio.run(svc.plan(None))
    assert len(svc.items()) == 4
    reloaded = ImportService(V1Source(v1), tmp_path / "import-plan.json", cat, lib, prep)  # type: ignore[arg-type]
    assert reloaded.items() == svc.items()
    assert snapshot(v1) == before


def test_decisions_persist_and_run_demands_the_right_source(setup, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    svc, v1, prep, lib, cat = setup
    asyncio.run(svc.plan(None))
    by_title = {i.v1.raw_title: i.v1.folder.name for i in svc.items()}
    svc.decide(by_title["陳奕迅 - 陀飛輪 (Official Music Video)"], "confirm", None)
    svc.decide(by_title["陳奕迅 Eason Chan《K歌之王》[Official MV]"], "confirm", None)
    with pytest.raises(ValueError):
        svc.decide(by_title["Unknown song"], "confirm", None)
    with pytest.raises(LookupError):
        svc.decide(by_title["Unknown song"], "correct", "expired")  # type: ignore[arg-type]

    online = asyncio.run(cat.search("陀飛輪")).online
    choice = asyncio.run(cat.resolve_video(online[0].key))  # type: ignore[index]
    assert not isinstance(choice, ChooseVideo)
    svc.decide(by_title["Unknown song"], "correct", choice.pick)

    reloaded = ImportService(V1Source(v1), tmp_path / "import-plan.json", cat, lib, prep)  # type: ignore[arg-type]
    assert [i.decision for i in reloaded.items()] == ["skipped", "confirmed", "confirmed", "corrected"]
    reloaded.run()
    sources = {r.song.id: r.source for r in prep.demand["import"]}
    assert isinstance(sources[SongId("v1kgezhiwan")], FromV1Files)
    assert isinstance(sources[SongId("omvtourbill")], FromYouTube)
    assert list(sources) == ["v1kgezhiwan", "omvtourbill"]
