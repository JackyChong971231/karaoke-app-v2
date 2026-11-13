"""A downloaded song's picture, kept beside its files (spec "Song pictures").

Phones load it from the laptop, so pictures show without YouTube at party time. Made once, on first request,
which also covers songs downloaded before this existed: YouTube's best picture for the video if the laptop can
reach it, else a frame from the downloaded video. Not one of the song's media files (`vocab.MediaFile`): a song
is complete without it, and losing it only means making it again.
"""

from __future__ import annotations

import asyncio
import logging
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from karaoke.core import SongId
from karaoke.songs.library import Library

log = logging.getLogger(__name__)

THUMB = "thumb.jpg"
Fetch = Callable[[SongId], bytes | None]
"""Blocking. The song's picture from YouTube, or None. Runs in a thread."""

_YOUTUBE_SIZES = ("maxresdefault", "hq720", "mqdefault")
"""Best first, all 16:9. The first two are missing for some videos (404); mqdefault always exists for a real video."""
_PLACEHOLDER_MAX_BYTES = 2048
"""For an unknown video YouTube answers 200 with a ~1 KB grey 120x90 image instead of a 404."""
_FETCH_TIMEOUT_S = 5
_FRAME_AT = 0.3
"""Share of the song to seek to for a frame: past an intro's black or title card, before the credits."""


def youtube_picture(song: SongId) -> bytes | None:
    for size in _YOUTUBE_SIZES:
        try:
            with urllib.request.urlopen(f"https://i.ytimg.com/vi/{song}/{size}.jpg", timeout=_FETCH_TIMEOUT_S) as r:
                data: bytes = r.read()
        except (urllib.error.URLError, TimeoutError, OSError):
            continue
        if len(data) > _PLACEHOLDER_MAX_BYTES:
            return data
    return None


def no_fetch(song: SongId) -> bytes | None:
    """The fake world: never touch the internet."""
    return None


class Thumbs:
    def __init__(self, library: Library, fetch: Fetch = youtube_picture) -> None:
        self._library = library
        self._fetch = fetch
        self._locks: dict[SongId, asyncio.Lock] = {}

    async def path(self, song: SongId) -> Path | None:
        """The picture's file, making it first if needed. None if the song is not downloaded or no picture
        could be made."""
        video = self._library.media_path(song, "video.mp4")
        if video is None:
            return None
        thumb = video.with_name(THUMB)
        if thumb.is_file():
            return thumb
        lock = self._locks.setdefault(song, asyncio.Lock())
        async with lock:
            if not thumb.is_file():
                await self._make(song, video, thumb)
        return thumb if thumb.is_file() else None

    async def _make(self, song: SongId, video: Path, thumb: Path) -> None:
        part = thumb.with_name(THUMB + ".part")
        data = await asyncio.to_thread(self._fetch, song)
        if data is not None:
            part.write_bytes(data)
        elif not await _frame(video, part, self._seconds(song)):
            log.warning("no picture for %s", song)
            return
        os.replace(part, thumb)

    def _seconds(self, song: SongId) -> float:
        record = self._library.get(song)
        return record.meta.duration_s * _FRAME_AT if record is not None else 0.0


async def _frame(video: Path, out: Path, at_s: float) -> bool:
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{at_s:.1f}", "-i", str(video),
            "-frames:v", "1", "-vf", "scale=1280:-2", "-q:v", "3", "-f", "image2", str(out),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    except OSError:
        return False
    _, err = await proc.communicate()
    if proc.returncode != 0:
        log.warning("ffmpeg frame failed for %s: %s", video, err.decode(errors="replace")[-300:])
        out.unlink(missing_ok=True)
        return False
    return out.is_file()
