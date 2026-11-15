"""One song's preparation, crash-safe and resumable. Private to karaoke.songs.prepare.

Staging layout (<library>/.staging/<video id>/):
    dl/                 yt-dlp's working folder (it resumes its own partial downloads)
    audio.src           downloaded audio (any container)            } step "downloading"
    video.mp4           <= 1080p, no audio track                    }
    instrumental.opus   160 kbit/s                                  } step "separating"
    vocals.opus                                                     }
    vocals.wav          kept for alignment, deleted before install  }
    lyrics.advanced.json  LyricsDoc v2, advanced lyrics matching (optional) } step "aligning"
    lyrics.advanced.tried the matching version that last ran              }
    lyrics.json         LyricsDoc, written last                     }

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
import tempfile
import time
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from karaoke.contract import LyricsDoc
from karaoke.core import SongId, SongMeta
from karaoke.songs.catalog import Catalog, SongNames
from karaoke.songs.library import ADVANCED_LYRICS
from karaoke.songs.prepare import _advanced_lyrics, _lyrics
from karaoke.songs.prepare._accelerator import Accelerator, Separate
from karaoke.songs.prepare._download import DownloadFailed, Downloader
from karaoke.songs.prepare._model import Device, FromV1Files, FromYouTube, Gate, PrepFailed, Progress, Source, Stages
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
            stage = step.stage
            await step.run(stages, song, source, staging, lambda p: report(stage, p))
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
        self._texts: dict[SongId, asyncio.Task[_lyrics.FoundLyrics | None]] = {}

    async def start(self) -> Device:
        task = asyncio.create_task(self._downloader.update_at_startup())
        self._background.add(task)
        task.add_done_callback(self._background.discard)
        return await self._accelerator.start()

    async def stop(self) -> None:
        await self._accelerator.stop()

    def _text(self, song: SongMeta) -> asyncio.Task[_lyrics.FoundLyrics | None]:
        if song.id not in self._texts:
            self._texts[song.id] = asyncio.create_task(self._find_text(song))
        return self._texts[song.id]

    async def _find_text(self, song: SongMeta) -> _lyrics.FoundLyrics | None:
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
        """lyrics.json, then advanced lyrics matching (lyrics.advanced.json). lyrics.json is written last, so a
        crash before it re-runs both. Advanced matching never fails the song."""
        t = time.monotonic()
        found = await self._text(song)
        del self._texts[song.id]
        log.info("%s: lyrics text ready after %.1fs more", song.id, time.monotonic() - t)
        t = time.monotonic()
        doc = await _lyrics.build(song, found.text if found else None, into / "vocals.wav", self._accelerator,
                                  lambda p: progress(0.4 * p))
        log.info("%s: alignment took %.1fs", song.id, time.monotonic() - t)
        await self._advanced(song.id, found if doc.source == "lrclib" else None, into / "vocals.wav", into, doc,
                             lambda p: progress(0.4 + 0.6 * p))
        write_doc(into / "lyrics.json", doc)

    async def advanced_lyrics(self, song: SongMeta, names: SongNames, folder: Path, gate: Gate) -> None:
        """Advanced lyrics matching for a song already in the library. The vocal WAV was deleted at install,
        so the vocal track is decoded again into a temporary folder."""
        found = await _lyrics.find_text(song, names)
        current = LyricsDoc.model_validate_json((folder / "lyrics.json").read_text("utf-8"))
        with tempfile.TemporaryDirectory(prefix="karaoke-advanced-") as tmp:
            wav = Path(tmp) / "vocals.wav"
            if found is not None:
                await ffmpeg("-i", folder / "vocals.opus", "-ac", "2", "-ar", "44100", "-f", "wav", wav)
            async with gate():
                await self._advanced(song.id, found, wav, folder, current, lambda p: None)

    async def _advanced(self, song: SongId, found: _lyrics.FoundLyrics | None, wav: Path, into: Path,
                        current: LyricsDoc, progress: Progress) -> None:
        """Writes lyrics.advanced.json when matching works, and the 'tried' marker either way, so the library
        job does not retry a song that cannot be matched. A crash writes no marker: the job retries it."""
        t = time.monotonic()
        try:
            doc = (await _advanced_lyrics.build_advanced(found, wav, self._accelerator, progress, current)
                   if found else None)
        except Exception:
            log.exception("%s: advanced lyrics matching crashed", song)
            return
        if doc is not None:
            write_doc(into / ADVANCED_LYRICS, doc)
        _advanced_lyrics.mark_tried(into)
        log.info("%s: advanced lyrics matching took %.1fs (%s)", song, time.monotonic() - t,
                 "written" if doc else "not matched")


def write_doc(path: Path, doc: LyricsDoc) -> None:
    part = path.with_name(path.name + ".part")
    part.write_text(doc.model_dump_json(by_alias=True, exclude_none=True), "utf-8")
    os.replace(part, path)
