"""The two fakes: YouTube Music (the internet edge) and the preparation stages (the network and GPU edge).

Everything between them, the Catalog rules, the Preparer scheduler, staging, and install, is the real code.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from karaoke.core import ArtistId, ArtistRef, SongId, SongMeta
from karaoke.harness.media import DURATION_S, Media, lyrics_doc
from karaoke.songs.library import Library, SongRecord
from karaoke.songs.prepare import FromV1Files, FromYouTube, PrepFailed, Source, Stages

FailMode = Literal["once", "always", "crash"]
EXPLODING_QUERY = "explode"
"""A search containing this word raises, which drives the phone's 'online search unavailable' note."""


@dataclass(frozen=True, slots=True)
class _Video:
    video_id: str
    title: str
    video_type: str
    artist_id: str
    artist_name: str


@dataclass(frozen=True, slots=True)
class _Song:
    atv: str
    zh_title: str
    en_title: str
    artist_id: str
    zh_artist: str
    en_artist: str
    videos: tuple[_Video, ...]


def _omv(video_id: str, title: str, artist_id: str, artist: str) -> _Video:
    return _Video(video_id, title, "MUSIC_VIDEO_TYPE_OMV", artist_id, artist)


def _ugc(video_id: str, title: str) -> _Video:
    return _Video(video_id, title, "MUSIC_VIDEO_TYPE_UGC", "UCrandomuploader", "Random Uploader")


CATALOG: tuple[_Song, ...] = (
    _Song("fkatv000001", "Fake Song One", "Fake Song One", "UCfakeArtistA", "Fake Artist", "Fake Artist",
          (_omv("fkomv000001", "Fake Artist - Fake Song One (Official Music Video)", "UCfakeArtistA", "Fake Artist"),)),
    _Song("fkatv000002", "測試之歌", "測試之歌", "UCfakeArtistB", "測試歌手", "Test Singer",
          (_omv("fkomv000002", "測試歌手《測試之歌》Official MV", "UCfakeArtistB", "測試歌手"),)),
    _Song("fkatv000003", "超複雜", "Complicated Fake", "UCfakeArtistC", "艾薇兒假", "Avril Fake",
          (_omv("fkomv000003", "Avril Fake - Complicated Fake (Official Video)", "UCfakeArtistC", "Avril Fake"),)),
    _Song("fkatv000004", "No Video Song", "No Video Song", "UCfakeArtistA", "Fake Artist", "Fake Artist",
          (_ugc("fkugc000041", "No Video Song (piano cover)"), _ugc("fkugc000042", "No Video Song lyrics"),
           _ugc("fkugc000043", "No Video Song live at home"))),
    _Song("fkatv000005", "Second Fake Hit", "Second Fake Hit", "UCfakeArtistA", "Fake Artist", "Fake Artist",
          (_omv("fkomv000005", "Fake Artist - Second Fake Hit (Official Music Video)", "UCfakeArtistA", "Fake Artist"),)),
)


def thumb(video_id: str) -> str:
    """Thumbnails are served by /test/thumb, so the pick-a-video grid renders with no network."""
    return f"/test/thumb/{video_id}.svg"


def _duration() -> dict[str, Any]:
    return {"duration": f"0:{int(DURATION_S):02d}", "duration_seconds": int(DURATION_S)}


class FakeYouTubeMusic:
    """Implements songs.catalog.YouTubeMusic with ytmusicapi-shaped dicts from CATALOG."""

    def search(self, query: str, language: str) -> list[dict[str, Any]]:
        q = query.casefold().strip()
        if EXPLODING_QUERY in q:
            raise RuntimeError("fake YouTube Music outage")
        if not q:
            return []
        hits = [s for s in CATALOG
                if any(q in t.casefold() for t in (s.zh_title, s.en_title, s.zh_artist, s.en_artist))]
        return [{"resultType": "song", **self._song(s, language)} for s in hits]

    def videos(self, query: str) -> list[dict[str, Any]]:
        q = query.casefold()
        return [
            {"resultType": "video", "videoId": v.video_id, "title": v.title, "videoType": v.video_type,
             "artists": [{"name": v.artist_name, "id": v.artist_id}], "thumbnails": [{"url": thumb(v.video_id), "width": 320, "height": 180}],
             **_duration()}
            for s in CATALOG if s.zh_artist.casefold() in q and s.zh_title.casefold() in q
            for v in s.videos
        ]

    def artist(self, artist: ArtistId, language: str) -> dict[str, Any]:
        songs = [s for s in CATALOG if s.artist_id == artist]
        if not songs:
            raise KeyError(artist)
        name = songs[0].en_artist if language == "en" else songs[0].zh_artist
        return {"name": name, "channelId": artist, "songs": {"results": [self._song(s, language) for s in songs]}}

    def track(self, video: SongId, language: str) -> dict[str, Any] | None:
        song = next((s for s in CATALOG if video == s.atv or any(v.video_id == video for v in s.videos)), None)
        return {**self._song(song, language), "videoId": video} if song else None

    @staticmethod
    def _song(s: _Song, language: str) -> dict[str, Any]:
        en = language == "en"
        return {
            "videoId": s.atv, "title": s.en_title if en else s.zh_title, "videoType": "MUSIC_VIDEO_TYPE_ATV",
            "artists": [{"name": s.en_artist if en else s.zh_artist, "id": s.artist_id}],
            "thumbnails": [{"url": thumb(s.atv), "width": 120, "height": 120}], **_duration(),
        }


class FakeStages(Stages):
    """Copies fixture media into staging. Each stage takes `delay_s`, or waits for /test/prep/<song>/advance
    when the song is held, and can be told to fail."""

    def __init__(self, media: Media, delay_s: float) -> None:
        self.media = media
        self.delay_s = delay_s
        self.calls: list[tuple[str, str]] = []
        self.updates = 0
        """How many times the 'download tool' was updated after a failure (fail mode 'once')."""
        self._held: dict[SongId, asyncio.Event] = {}
        self._fail: dict[SongId, FailMode] = {}

    def hold(self, song: SongId) -> None:
        self._held.setdefault(song, asyncio.Event())

    def release(self, song: SongId) -> None:
        gate = self._held.pop(song, None)
        if gate:
            gate.set()

    def advance(self, song: SongId) -> None:
        """Let the held song's current (or next) stage finish."""
        self.hold(song)
        self._held[song].set()

    def fail(self, song: SongId, mode: FailMode) -> None:
        self._fail[song] = mode

    def describe(self) -> dict[str, Any]:
        return {"calls": [list(x) for x in self.calls], "updates": self.updates,
                "held": sorted(self._held), "failing": dict(self._fail), "delayS": self.delay_s}

    async def _stage(self, song: SongId, stage: str, progress: Any) -> None:
        self.calls.append((stage, song))
        gate = self._held.get(song)
        if gate is not None:
            await gate.wait()
            gate.clear()
            return
        steps = 4
        for i in range(1, steps + 1):
            await asyncio.sleep(self.delay_s / steps)
            progress(i / steps)

    async def download(self, song: SongMeta, source: Source, into: Path, progress: Any) -> None:
        await self._stage(song.id, "download", progress)
        mode = self._fail.get(song.id)
        if mode == "always":
            raise PrepFailed("cant_download", "fake download failure")
        if mode == "once":
            # The real downloader updates yt-dlp and retries once inside fetch(); this mirrors that.
            self.updates += 1
            del self._fail[song.id]
        _put(self.media.video(song.id), into / "video.mp4")
        match source:
            case FromYouTube():
                _put(self.media.instrumental, into / "audio.src")
            case FromV1Files():
                _put(self.media.instrumental, into / "instrumental.opus")
                _put(self.media.vocals, into / "vocals.opus")
                _put(self.media.vocals_wav, into / "vocals.wav")

    async def separate(self, into: Path, progress: Any) -> None:
        song = SongId(into.name)
        await self._stage(song, "separate", progress)
        if self._fail.get(song) == "crash":
            del self._fail[song]
            raise RuntimeError("fake accelerator crash mid-separation")
        _put(self.media.instrumental, into / "instrumental.opus")
        _put(self.media.vocals, into / "vocals.opus")
        _put(self.media.vocals_wav, into / "vocals.wav")

    async def lyrics(self, song: SongMeta, into: Path, progress: Any) -> None:
        await self._stage(song.id, "lyrics", progress)
        _write(into / "lyrics.json", lyrics_doc().model_dump_json(by_alias=True))


def _put(src: Path, dst: Path) -> None:
    part = dst.with_name(dst.name + ".part")
    shutil.copyfile(src, part)
    os.replace(part, dst)


def _write(dst: Path, text: str) -> None:
    part = dst.with_name(dst.name + ".part")
    part.write_text(text, encoding="utf-8")
    os.replace(part, dst)


SEED: tuple[tuple[SongMeta, tuple[str, ...], bool], ...] = (
    (SongMeta(SongId("fklib000001"), "Morning Sun", ArtistRef(ArtistId("UCfakeLibBand"), "Library Band"), DURATION_S),
     ("Library Band", "圖書館樂隊"), False),
    (SongMeta(SongId("fklib000002"), "河流", ArtistRef(ArtistId("UCfakeLibSinger"), "圖書館歌手"), DURATION_S),
     ("圖書館歌手", "Library Singer"), False),
    (SongMeta(SongId("fklib000003"), "Night Drive", ArtistRef(ArtistId("UCfakeLibBand"), "Library Band"), DURATION_S),
     ("Library Band",), True),
)
"""Library songs at boot: ready to queue at once, and the filler pool. Night Drive has transcribed lyrics."""


def seed_library(library: Library, media: Media) -> None:
    for meta, names, transcribed in SEED:
        if library.has(meta.id):
            continue
        d = library.staging_dir(meta.id)
        _put(media.video(meta.id), d / "video.mp4")
        _put(media.instrumental, d / "instrumental.opus")
        _put(media.vocals, d / "vocals.opus")
        _write(d / "lyrics.json", lyrics_doc(transcribed).model_dump_json(by_alias=True))
        library.install(meta.id, SongRecord(
            meta=meta, artist_names=names, alt_titles=(meta.title,), language="en",
            lyrics_source="transcribed" if transcribed else "lrclib",
            source_url=f"https://www.youtube.com/watch?v={meta.id}",
        ))
