"""One song's preparation, crash-safe and resumable. Private to karaoke.songs.prepare.

Staging layout (<library>/.staging/<video id>/):
    dl/                 yt-dlp's working folder (it resumes its own partial downloads)
    audio.src           downloaded audio (any container)            } step "downloading"
    video.mp4           <= 1080p, no audio track                    }
    instrumental.opus   160 kbit/s                                  } step "separating"
    vocals.opus                                                     }
    vocals.wav          kept for alignment, deleted before install  }
    lyrics.json         LyricsDoc                                   } step "aligning"

Crash-safety rules:
1. Every output is written as <name>.part then os.replace'd to <name>. A visible <name> is complete.
2. A step is done when all its outputs exist. There are no marker files. Intermediates are deleted only
   after the last step, so the last step whose outputs all exist marks every step before it as done.
3. Staging is keyed by song id, not attempt, so a retry after a crash or restart resumes at the first
   step that is not done. On CPU that saves up to 3 minutes per interrupted song.
4. Library.install is the only exit from staging, and it is one directory rename.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sys
import time
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from karaoke.core import SongId, SongMeta
from karaoke.songs.catalog import Catalog
from karaoke.songs.prepare import _lyrics
from karaoke.songs.prepare._accelerator import Accelerator, Separate
from karaoke.songs.prepare._download import DownloadFailed, Downloader
from karaoke.songs.prepare._model import Device, FromV1Files, FromYouTube, PrepFailed, Progress, Source, Stages
from karaoke.vocab import PrepStage

log = logging.getLogger(__name__)

Resource = Literal["download", "accelerator"]
Slot = Callable[[Resource, SongId], AbstractAsyncContextManager[None]]
Report = Callable[[PrepStage, float | None], None]


@dataclass(frozen=True, slots=True)
class Step:
    stage: PrepStage
    resource: Resource
    outputs: tuple[str, ...]
    run: Callable[[Stages, SongMeta, Source, Path, Progress], Awaitable[None]]


def _download(st: Stages, song: SongMeta, src: Source, d: Path, p: Progress) -> Awaitable[None]:
    return st.download(song, src, d, p)


def _separate(st: Stages, song: SongMeta, src: Source, d: Path, p: Progress) -> Awaitable[None]:
    return st.separate(d, p)


def _align(st: Stages, song: SongMeta, src: Source, d: Path, p: Progress) -> Awaitable[None]:
    return st.lyrics(song, d, p)


LYRICS = Step("aligning", "accelerator", ("lyrics.json",), _align)
PLANS: dict[type, tuple[Step, ...]] = {
    FromYouTube: (
        Step("downloading", "download", ("video.mp4", "audio.src"), _download),
        Step("separating", "accelerator", ("instrumental.opus", "vocals.opus", "vocals.wav"), _separate),
        LYRICS,
    ),
    FromV1Files: (
        Step("downloading", "download", ("video.mp4", "instrumental.opus", "vocals.opus", "vocals.wav"), _download),
        LYRICS,
    ),
}
INTERMEDIATES = ("dl", "audio.src", "mix.wav", "instrumental.wav", "vocals.wav")


def pending_steps(source: Source, staging: Path) -> tuple[Step, ...]:
    plan = PLANS[type(source)]
    done = max((i + 1 for i, s in enumerate(plan) if all((staging / f).exists() for f in s.outputs)), default=0)
    return plan[done:]


async def prepare_song(song: SongMeta, source: Source, staging: Path, stages: Stages, report: Report,
                       slot: Slot) -> None:
    """Run the steps that are not done, in order. Raises PrepFailed on a final failure."""
    for step in pending_steps(source, staging):
        report("waiting", None)
        async with slot(step.resource, song.id):
            report(step.stage, 0.0)
            await step.run(stages, song, source, staging, lambda p, s=step.stage: report(s, p))
        missing = [f for f in step.outputs if not (staging / f).exists()]
        if missing:
            raise PrepFailed("processing_crashed", f"{step.stage} did not produce {missing}")
    for name in INTERMEDIATES:
        p = staging / name
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        else:
            p.unlink(missing_ok=True)


# ---- the real stages ----

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


async def ffmpeg(*args: str | Path) -> None:
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *map(str, args),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE, creationflags=_NO_WINDOW)
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise PrepFailed("processing_crashed", f"ffmpeg: {err.decode(errors='replace')[-400:]}")


async def to_opus(src: Path, dst: Path) -> None:
    part = dst.with_name(dst.name + ".part")
    await ffmpeg("-i", src, "-vn", "-c:a", "libopus", "-b:a", "160k", "-f", "ogg", part)
    os.replace(part, dst)


async def strip_audio(src: Path, dst: Path) -> None:
    part = dst.with_name(dst.name + ".part")
    await ffmpeg("-i", src, "-an", "-c:v", "copy", "-movflags", "+faststart", "-f", "mp4", part)
    os.replace(part, dst)


async def copy_file(src: Path, dst: Path) -> None:
    part = dst.with_name(dst.name + ".part")
    await asyncio.to_thread(shutil.copyfile, src, part)
    os.replace(part, dst)


class RealStages(Stages):
    """Wires the stage contracts to yt-dlp (_download), Demucs + stable-ts (_accelerator), LRCLIB (_lyrics)."""

    def __init__(self, catalog: Catalog) -> None:
        self._catalog = catalog
        self._downloader = Downloader()
        self._accelerator = Accelerator()
        self._background: set[asyncio.Task[None]] = set()
        self._texts: dict[SongId, asyncio.Task[str | None]] = {}

    async def start(self) -> Device:
        task = asyncio.create_task(self._downloader.update_at_startup())
        self._background.add(task)
        task.add_done_callback(self._background.discard)
        return await self._accelerator.start()

    async def stop(self) -> None:
        await self._accelerator.stop()

    def _text(self, song: SongMeta) -> asyncio.Task[str | None]:
        if song.id not in self._texts:
            self._texts[song.id] = asyncio.create_task(self._find_text(song))
        return self._texts[song.id]

    async def _find_text(self, song: SongMeta) -> str | None:
        return await _lyrics.find_text(song, await self._catalog.describe(song))

    async def download(self, song: SongMeta, source: Source, into: Path, progress: Progress) -> None:
        self._text(song)
        match source:
            case FromYouTube():
                try:
                    await self._downloader.fetch(song.id, into, progress)
                except DownloadFailed as e:
                    raise PrepFailed("video_unavailable" if e.kind == "unavailable" else "cant_download", str(e))
            case FromV1Files(video=video, instrumental=instrumental, vocals=vocals):
                await strip_audio(video, into / "video.mp4")
                await asyncio.gather(to_opus(instrumental, into / "instrumental.opus"),
                                     to_opus(vocals, into / "vocals.opus"), copy_file(vocals, into / "vocals.wav"))

    async def separate(self, into: Path, progress: Progress) -> None:
        """audio.src -> 44.1 kHz wav -> htdemucs -> instrumental/vocals wav -> opus 160k."""
        t = time.monotonic()
        if not ((into / "instrumental.wav").exists() and (into / "vocals.wav").exists()):
            mix = into / "mix.wav"
            if not mix.exists():
                part = into / "mix.wav.part"
                await ffmpeg("-i", into / "audio.src", "-vn", "-ac", "2", "-ar", "44100", "-f", "wav", part)
                os.replace(part, mix)
            log.info("%s: audio decoded in %.1fs", into.name, time.monotonic() - t)
            t = time.monotonic()
            await self._accelerator.run(Separate(mix, into), progress)
            log.info("%s: htdemucs took %.1fs", into.name, time.monotonic() - t)
            t = time.monotonic()
        await asyncio.gather(to_opus(into / "instrumental.wav", into / "instrumental.opus"),
                             to_opus(into / "vocals.wav", into / "vocals.opus"))
        log.info("%s: opus encoding took %.1fs", into.name, time.monotonic() - t)

    async def lyrics(self, song: SongMeta, into: Path, progress: Progress) -> None:
        t = time.monotonic()
        text = await self._text(song)
        del self._texts[song.id]
        log.info("%s: lyrics text ready after %.1fs more", song.id, time.monotonic() - t)
        t = time.monotonic()
        doc = await _lyrics.build(song, text, into / "vocals.wav", self._accelerator, progress)
        part = into / "lyrics.json.part"
        part.write_text(doc.model_dump_json(by_alias=True), "utf-8")
        os.replace(part, into / "lyrics.json")
        log.info("%s: alignment took %.1fs", song.id, time.monotonic() - t)
