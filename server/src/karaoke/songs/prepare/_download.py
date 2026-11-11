"""yt-dlp as an external tool in its own `uv tool` environment, plus Deno. Private.

The rest of the app never sees yt-dlp's arguments, output, or version.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from karaoke.core import SongId

VIDEO_FORMAT = "bv*[height<=1080][vcodec^=avc1]/bv*[height<=1080]"   # TV size; remuxed to mp4, no audio
AUDIO_FORMAT = "ba/b"


class DownloadFailed(Exception):
    """kind: 'unavailable' (private/removed video: no retry helps) or 'tool' (anything else)."""


class Downloader:
    def __init__(self) -> None:
        self._update_lock = asyncio.Lock()
        self._updated_after_failure_at: float | None = None

    async def update_at_startup(self) -> None:
        """`uv tool upgrade yt-dlp` in the background at boot. Never blocks the party; a failure is logged."""
        raise NotImplementedError

    async def fetch(self, video: SongId, into: Path, progress: Callable[[float], None]) -> None:
        """Download audio.src and video.mp4 in parallel.

        TODO pseudocode (update and retry once, single-flight):
            try: await _both(video, into, progress)
            except DownloadFailed as e:
                if e.kind == "unavailable": raise
                await _update_once()       # if several downloads fail together, ONE update runs; the others
                                           # wait on the lock and see it already happened in the last 10 min
                await _both(video, into, progress)   # second failure propagates -> 'cant_download'
        """
        raise NotImplementedError

    async def _update_once(self) -> None:
        raise NotImplementedError
