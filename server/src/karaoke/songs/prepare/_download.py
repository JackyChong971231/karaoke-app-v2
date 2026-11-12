"""yt-dlp as an external tool in its own `uv tool` environment, plus Deno. Private.

The rest of the app never sees yt-dlp's arguments, output, or version.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import sys
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from karaoke.core import SongId

log = logging.getLogger(__name__)

VIDEO_FORMAT = "bv[height<=1080][vcodec^=avc1]/bv[height<=1080]"   # TV size, video-only stream; remuxed to mp4
AUDIO_FORMAT = "ba/b"
UPDATE_FRESH_S = 600
_UNAVAILABLE = re.compile(
    r"Video unavailable|Private video|has been removed|no longer available|account associated with this video"
    r"|not available in your country|members-only|confirm your age", re.I)
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _tool(name: str) -> str:
    return shutil.which(name) or str(Path.home() / ".local" / "bin" / f"{name}.exe")


class DownloadFailed(Exception):
    def __init__(self, kind: Literal["unavailable", "tool"], detail: str) -> None:
        super().__init__(detail)
        self.kind = kind
        """'unavailable' (private/removed video: no retry helps) or 'tool' (anything else)."""


class Downloader:
    def __init__(self) -> None:
        self._update_lock = asyncio.Lock()
        self._updated_at: float | None = None

    async def update_at_startup(self) -> None:
        """`uv tool upgrade yt-dlp` in the background at boot. Never blocks the party; a failure is logged."""
        await self._update_once()

    async def fetch(self, video: SongId, into: Path, progress: Callable[[float], None]) -> None:
        """Download audio.src and video.mp4 in parallel. After a tool failure, update yt-dlp once
        (single-flight across concurrent downloads) and retry once."""
        async with self._update_lock:
            pass
        try:
            await self._both(video, into, progress)
        except DownloadFailed as e:
            if e.kind == "unavailable":
                raise
            log.warning("download of %s failed, updating yt-dlp and retrying: %s", video, e)
            await self._update_once()
            await self._both(video, into, progress)

    async def _update_once(self) -> None:
        async with self._update_lock:
            if self._updated_at and time.monotonic() - self._updated_at < UPDATE_FRESH_S:
                return
            try:
                proc = await asyncio.create_subprocess_exec(
                    _tool("uv"), "tool", "upgrade", "yt-dlp", stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT, creationflags=_NO_WINDOW)
                out, _ = await proc.communicate()
                log.info("yt-dlp update exited %s: %s", proc.returncode, out.decode(errors="replace").strip()[-300:])
            except OSError as e:
                log.warning("yt-dlp update failed to start: %s", e)
            self._updated_at = time.monotonic()

    async def _both(self, video: SongId, into: Path, progress: Callable[[float], None]) -> None:
        work = into / "dl"
        work.mkdir(exist_ok=True)
        parts = {"audio.src": 0.0, "video.mp4": 0.0}

        def report(name: str) -> Callable[[float], None]:
            def on(p: float) -> None:
                parts[name] = p
                progress(sum(parts.values()) / len(parts))
            return on

        jobs = []
        if not (into / "audio.src").exists():
            jobs.append(self._one(video, work, "audio", AUDIO_FORMAT, [], into / "audio.src", report("audio.src")))
        if not (into / "video.mp4").exists():
            jobs.append(self._one(video, work, "video", VIDEO_FORMAT, ["--remux-video", "mp4"], into / "video.mp4",
                                  report("video.mp4")))
        results = await asyncio.gather(*jobs, return_exceptions=True)
        failures = [r for r in results if isinstance(r, BaseException)]
        if failures:
            unavailable = [f for f in failures if isinstance(f, DownloadFailed) and f.kind == "unavailable"]
            raise (unavailable or failures)[0]

    async def _one(self, video: SongId, work: Path, name: str, fmt: str, extra: list[str], dst: Path,
                   progress: Callable[[float], None]) -> None:
        args = [
            _tool("yt-dlp"), "--no-playlist", "--newline", "--no-mtime", "--no-warnings",
            "-f", fmt, *extra, "-o", str(work / f"{name}.%(ext)s"),
            "--progress-template", "download:KP %(progress.downloaded_bytes)s %(progress.total_bytes)s "
                                   "%(progress.total_bytes_estimate)s",
            f"https://www.youtube.com/watch?v={video}",
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, creationflags=_NO_WINDOW)
        except OSError as e:
            raise DownloadFailed("tool", f"cannot start yt-dlp: {e}") from e
        started = time.monotonic()
        tail: deque[str] = deque(maxlen=40)
        assert proc.stdout
        async for raw in proc.stdout:
            line = raw.decode(errors="replace").strip()
            if line.startswith("KP "):
                p = _fraction(line.split()[1:])
                if p is not None:
                    progress(p)
            elif line:
                tail.append(line)
        await proc.wait()
        log.info("yt-dlp %s %s exited %s after %.1fs", name, video, proc.returncode, time.monotonic() - started)
        text = "\n".join(tail)
        if proc.returncode != 0:
            raise DownloadFailed("unavailable" if _UNAVAILABLE.search(text) else "tool", text[-600:])
        done = [p for p in work.glob(f"{name}.*") if p.suffix not in (".part", ".ytdl") and ".part" not in p.name]
        target = work / "video.mp4" if name == "video" else (done[0] if done else None)
        if target is None or not target.exists():
            raise DownloadFailed("tool", f"yt-dlp produced no {name} file: {text[-300:]}")
        os.replace(target, dst)
        progress(1.0)


def _fraction(fields: list[str]) -> float | None:
    try:
        done = float(fields[0])
        total = next(float(f) for f in fields[1:] if f not in ("NA", "None"))
        return min(1.0, done / total) if total > 0 else None
    except (ValueError, StopIteration, IndexError):
        return None
