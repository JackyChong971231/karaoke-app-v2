import asyncio
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from karaoke.contract import LyricsDoc
from karaoke.core import ArtistId, ArtistRef, SongId, SongMeta
from karaoke.songs.catalog import SongNames
from karaoke.songs.library import Library
from karaoke.songs.prepare import FromV1Files, FromYouTube, PrepFailed, PrepRequest, Preparer, Source, Stages
from karaoke.songs.prepare._pipeline import pending_steps


def meta(vid: str) -> SongMeta:
    return SongMeta(SongId(vid), f"title {vid}", ArtistRef(ArtistId("UCa"), "A"), 100.0)


def touch(d: Path, *names: str) -> None:
    for n in names:
        (d / n).write_bytes(b"x")


class FakeStages(Stages):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.active: Counter[str] = Counter()
        self.peak: Counter[str] = Counter()
        self.fail_separate: set[str] = set()
        self.hold_downloads = asyncio.Event()
        self.hold_downloads.set()

    async def _busy(self, kind: str, song: str) -> None:
        self.calls.append((kind, song))
        self.active[kind] += 1
        self.peak[kind] = max(self.peak[kind], self.active[kind])
        await asyncio.sleep(0.02)
        self.active[kind] -= 1

    async def download(self, song: SongMeta, source: Source, into: Path, progress: Callable[[float], None]) -> None:
        await self.hold_downloads.wait()
        await self._busy("download", song.id)
        touch(into, "video.mp4", "audio.src") if isinstance(source, FromYouTube) else \
            touch(into, "video.mp4", "instrumental.opus", "vocals.opus", "vocals.wav")

    async def separate(self, into: Path, progress: Callable[[float], None]) -> None:
        await self._busy("accel", into.name)
        self.calls.append(("separate", into.name))
        if into.name in self.fail_separate:
            raise PrepFailed("processing_crashed")
        touch(into, "instrumental.opus", "vocals.opus", "vocals.wav")

    async def lyrics(self, song: SongMeta, into: Path, progress: Callable[[float], None]) -> None:
        await self._busy("accel", song.id)
        self.calls.append(("lyrics", song.id))
        doc = LyricsDoc(version=1, source="lrclib", language="zh", lines=[])
        (into / "lyrics.json").write_text(doc.model_dump_json(by_alias=True), "utf-8")


class Names:
    async def describe(self, song: SongMeta) -> SongNames:
        return SongNames((song.artist.name, "Alias"), (song.title,))


class World:
    def __init__(self, tmp: Path) -> None:
        self.library = Library(tmp / "lib")
        self.library.open()
        self.stages = FakeStages()
        self.ready: list[str] = []
        self.preparer = Preparer(self.library, Names(), self.stages, self.ready.append, lambda: None)  # type: ignore[arg-type]

    async def until(self, cond: Callable[[], bool], timeout: float = 5.0) -> None:
        async def poll() -> None:
            while not cond():
                await asyncio.sleep(0.01)
        await asyncio.wait_for(poll(), timeout)


def run(tmp: Path, scenario: Callable[[World], object]) -> World:
    world = World(tmp)

    async def main() -> None:
        task = asyncio.create_task(world.preparer.run())
        try:
            await scenario(world)  # type: ignore[misc]
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(main())
    return world


def test_a_step_is_done_when_its_outputs_exist(tmp_path: Path) -> None:
    yt, v1 = FromYouTube(), FromV1Files(Path("v"), Path("i"), Path("o"))
    assert [s.stage for s in pending_steps(yt, tmp_path)] == ["downloading", "separating", "aligning"]
    touch(tmp_path, "video.mp4", "audio.src")
    assert [s.stage for s in pending_steps(yt, tmp_path)] == ["separating", "aligning"]
    touch(tmp_path, "instrumental.opus", "vocals.opus")
    assert [s.stage for s in pending_steps(yt, tmp_path)] == ["separating", "aligning"]
    touch(tmp_path, "vocals.wav")
    assert [s.stage for s in pending_steps(yt, tmp_path)] == ["aligning"]
    assert [s.stage for s in pending_steps(v1, tmp_path)] == ["aligning"]
    touch(tmp_path, "lyrics.json")
    for name in ("audio.src", "vocals.wav"):
        (tmp_path / name).unlink()
    assert pending_steps(yt, tmp_path) == ()


def test_partial_files_do_not_count(tmp_path: Path) -> None:
    touch(tmp_path, "video.mp4", "audio.src.part")
    assert pending_steps(FromYouTube(), tmp_path)[0].stage == "downloading"


def test_all_demand_is_prepared_with_two_downloads_one_accelerator_and_party_first(tmp_path: Path) -> None:
    async def scenario(w: World) -> None:
        w.preparer.set_demand("import", [PrepRequest(meta("imp1")), PrepRequest(meta("imp2"))])
        w.preparer.set_demand("party", [PrepRequest(meta(f"p{i}")) for i in range(3)])
        await w.until(lambda: len(w.ready) == 5)

    w = run(tmp_path, scenario)
    assert sorted(w.ready) == ["imp1", "imp2", "p0", "p1", "p2"]
    assert all(w.library.has(SongId(s)) for s in w.ready)
    assert w.stages.peak["download"] == 2 and w.stages.peak["accel"] == 1
    separated = [s for k, s in w.stages.calls if k == "separate"]
    assert separated.index("p2") < separated.index("imp1")
    record = w.library.get(SongId("p0"))
    assert record and record.artist_names == ("A", "Alias") and record.lyrics_source == "lrclib"
    assert not any((w.library.root / ".staging").iterdir())


def test_a_failed_song_resumes_without_redownloading_after_it_is_demanded_again(tmp_path: Path) -> None:
    async def scenario(w: World) -> None:
        w.stages.fail_separate.add("s1")
        w.preparer.set_demand("party", [PrepRequest(meta("s1"))])
        await w.until(lambda: w.preparer.board().get(SongId("s1"), None) is not None
                      and w.preparer.board()[SongId("s1")].stage == "failed")
        assert w.preparer.board()[SongId("s1")].failure == "processing_crashed"
        w.preparer.set_demand("party", [PrepRequest(meta("s1"))])
        await asyncio.sleep(0.1)
        assert w.preparer.board()[SongId("s1")].stage == "failed"
        w.stages.fail_separate.clear()
        w.preparer.set_demand("party", [])
        w.preparer.set_demand("party", [PrepRequest(meta("s1"))])
        await w.until(lambda: w.ready == ["s1"])

    w = run(tmp_path, scenario)
    assert [k for k, s in w.stages.calls if s == "s1"].count("download") == 1
    assert [k for k, s in w.stages.calls if s == "s1"].count("separate") == 2


def test_library_songs_are_ready_at_once_and_never_prepared(tmp_path: Path) -> None:
    async def scenario(w: World) -> None:
        w.preparer.set_demand("party", [PrepRequest(meta("lib1"))])
        await w.until(lambda: w.ready == ["lib1"])
        w.ready.clear()
        w.preparer.set_demand("party", [PrepRequest(meta("lib1"))])
        assert w.ready == ["lib1"]

    w = run(tmp_path, scenario)
    assert [k for k, s in w.stages.calls if s == "lib1"].count("download") == 1


def test_a_song_that_leaves_demand_before_its_download_starts_is_dropped(tmp_path: Path) -> None:
    async def scenario(w: World) -> None:
        w.stages.hold_downloads.clear()
        w.preparer.set_demand("party", [PrepRequest(meta(x)) for x in ("a", "b", "c")])
        await asyncio.sleep(0.05)
        w.preparer.set_demand("party", [PrepRequest(meta("a")), PrepRequest(meta("b"))])
        await w.until(lambda: SongId("c") not in w.preparer.board())
        w.stages.hold_downloads.set()
        await w.until(lambda: len(w.ready) == 2)
        await asyncio.sleep(0.05)

    w = run(tmp_path, scenario)
    assert sorted(w.ready) == ["a", "b"]
    assert ("download", "c") not in w.stages.calls


def test_v1_files_skip_separation(tmp_path: Path) -> None:
    async def scenario(w: World) -> None:
        w.preparer.set_demand("import", [PrepRequest(meta("v1song"), FromV1Files(Path("v"), Path("i"), Path("o")))])
        await w.until(lambda: w.ready == ["v1song"])

    w = run(tmp_path, scenario)
    assert [k for k, s in w.stages.calls if s == "v1song"] == ["download", "accel", "lyrics"]
