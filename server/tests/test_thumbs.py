"""Spec "Song pictures": a downloaded song's picture comes from the laptop, made once."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from karaoke.core import ArtistId, ArtistRef, SongId, SongMeta
from karaoke.harness.media import ensure_media
from karaoke.songs.library import Library, SongRecord
from karaoke.songs.thumbs import THUMB, Thumbs, no_fetch

SONG = SongId("vidthumb001")
JPEG = b"\xff\xd8" + b"y" * 5000


def library_with_song(tmp_path: Path, video: Path | None = None) -> Library:
    library = Library(tmp_path / "lib")
    library.open()
    d = library.staging_dir(SONG)
    for f in ("instrumental.opus", "vocals.opus", "lyrics.json"):
        (d / f).write_bytes(b"x")
    if video is None:
        (d / "video.mp4").write_bytes(b"x")
    else:
        shutil.copy(video, d / "video.mp4")
    meta = SongMeta(SONG, "歌", ArtistRef(ArtistId("UCx"), "歌手"), 10.0)
    library.install(SONG, SongRecord(meta, ("歌手",), ("歌",), "zh", "lrclib", ""))
    return library


def test_takes_youtubes_picture_once(tmp_path: Path) -> None:
    calls: list[SongId] = []

    def fetch(song: SongId) -> bytes | None:
        calls.append(song)
        return JPEG

    thumbs = Thumbs(library_with_song(tmp_path), fetch)
    first = asyncio.run(thumbs.path(SONG))
    assert first is not None and first.name == THUMB and first.read_bytes() == JPEG
    assert asyncio.run(thumbs.path(SONG)) == first
    assert calls == [SONG], "kept beside the song, not fetched again"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_falls_back_to_a_frame_of_the_downloaded_video(tmp_path: Path) -> None:
    video = ensure_media(tmp_path / "media").video(SONG)
    thumbs = Thumbs(library_with_song(tmp_path, video), no_fetch)
    path = asyncio.run(thumbs.path(SONG))
    assert path is not None and path.read_bytes()[:2] == b"\xff\xd8", "a JPEG frame"


def test_no_picture_for_a_song_not_downloaded(tmp_path: Path) -> None:
    thumbs = Thumbs(library_with_song(tmp_path), lambda s: JPEG)
    assert asyncio.run(thumbs.path(SongId("notdownload"))) is None
    assert asyncio.run(thumbs.path(SongId("../escape"))) is None
