"""Preparation: turn a SongMeta into a complete library folder.

Public surface is the Preparer class and its status types. The stage code (_pipeline, _download,
_accelerator, _lyrics) is private: import-linter forbids importing it from outside this package.

The Preparer is a RECONCILER, not a job API. Callers never "start" or "cancel" a job. They declare the
full ordered list of songs they want (`set_demand`), and the Preparer works toward it. That makes every
call idempotent, makes restart recovery the same code path as normal operation, and leaves the party
reducer with nothing to remember about jobs.

States per song (the board):

    waiting --> downloading --> waiting --> separating --> waiting --> aligning --> ready
                                                           (current lyrics, then advanced lyrics matching)
       ^                 (for the accelerator)        |                    |
       |            +---------------------------------+--------------------+--> failed(reason)
       +-- (retry: song leaves all demand, then is demanded again)

The board holds only songs that are demanded or still running. 'ready' is reported to the party as
SongReady; it is also reported immediately for songs already on disk.
"""

from __future__ import annotations

import asyncio
import errno
import logging
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from types import MappingProxyType

from karaoke.contract import LyricsDoc
from karaoke.core import SongId
from karaoke.songs.catalog import Catalog, SongNames
from karaoke.songs.library import Library, SongRecord
from karaoke.songs.prepare import _advanced_lyrics
from karaoke.songs.prepare._model import (
    Device, FromV1Files, FromYouTube, Gate, Lane, PrepFailed, PrepRequest, PrepStatus, Source, Stages,
)
from karaoke.songs.prepare._pipeline import RealStages, Resource, prepare_song
from karaoke.vocab import FailReason, PrepStage

__all__ = [
    "Device", "FromV1Files", "FromYouTube", "Gate", "Lane", "PrepFailed", "PrepRequest", "PrepStatus", "Preparer",
    "RealStages", "Source", "Stages",
]

log = logging.getLogger(__name__)

LANES: tuple[Lane, ...] = ("party", "import")
DOWNLOADS = 2
BOARD_HZ = 2.0
Rank = tuple[int, int]
_UNDEMANDED: Rank = (len(LANES), 0)


class _Dropped(Exception):
    """The song left all demand before its download started."""


class _Gate:
    """Capacity-limited admission in priority order. Priority is read when a slot frees, so a song moved
    to 'play next' jumps the line. `rank` returning None turns a waiter away."""

    def __init__(self, capacity: int, rank: Callable[[SongId], Rank | None]) -> None:
        self._capacity = capacity
        self._rank = rank
        self._busy = 0
        self._waiting: dict[SongId, asyncio.Future[bool]] = {}

    @asynccontextmanager
    async def hold(self, song: SongId) -> AsyncIterator[None]:
        fut: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._waiting[song] = fut
        self.pump()
        if not await fut:
            raise _Dropped()
        try:
            yield
        finally:
            self._busy -= 1
            self.pump()

    def pump(self) -> None:
        for song in [s for s in self._waiting if self._rank(s) is None]:
            self._waiting.pop(song).set_result(False)
        while self._busy < self._capacity and self._waiting:
            song = min(self._waiting, key=lambda s: self._rank(s) or _UNDEMANDED)
            self._waiting.pop(song).set_result(True)
            self._busy += 1


class Preparer:
    def __init__(
        self,
        library: Library,
        catalog: Catalog,
        stages: Stages,
        on_ready: Callable[[SongId], None],
        on_board_change: Callable[[], None],
    ) -> None:
        """`stages` is the real pipeline or the harness fake (same scheduler either way).
        Callbacks are invoked on the asyncio loop thread; the shell turns on_ready into a SongReady input."""
        self._library = library
        self._catalog = catalog
        self._stages = stages
        self._on_ready = on_ready
        self._on_board_change = on_board_change
        self._device: Device = "cpu"
        self._demand: dict[Lane, tuple[PrepRequest, ...]] = {lane: () for lane in LANES}
        self._ranks: dict[SongId, Rank] = {}
        self._requests: dict[SongId, PrepRequest] = {}
        self._board: dict[SongId, PrepStatus] = {}
        self._jobs: dict[SongId, asyncio.Task[None]] = {}
        self._downloads = _Gate(DOWNLOADS, self._ranks.get)
        self._accelerator = _Gate(1, lambda s: self._ranks.get(s, _UNDEMANDED))
        self._wake = asyncio.Event()
        self._flush: asyncio.TimerHandle | None = None
        self._last_flush = 0.0

    @property
    def device(self) -> Device:
        """Probed once at boot inside the accelerator process: cuda if torch.cuda.is_available(), else cpu.
        Shown on the phone settings screen. Nothing else in the app branches on it."""
        return self._device

    def set_demand(self, lane: Lane, wanted: Sequence[PrepRequest]) -> None:
        """Replace this lane's demand with `wanted` (ordered, most urgent first). Idempotent.
        A running job whose song leaves demand is not cancelled: it finishes and lands in the library."""
        self._demand[lane] = tuple(wanted)
        self._ranks.clear()
        self._requests.clear()
        for li, ln in enumerate(LANES):
            for i, r in enumerate(self._demand[ln]):
                self._ranks.setdefault(r.song.id, (li, i))
                self._requests.setdefault(r.song.id, r)
        for song in self._ranks:
            if self._library.has(song):
                self._on_ready(song)
            elif song not in self._board:
                self._board[song] = PrepStatus("waiting")
        for song in [s for s in self._board if s not in self._ranks and s not in self._jobs]:
            del self._board[song]
        self._downloads.pump()
        self._accelerator.pump()
        self._wake.set()
        self._changed()

    def board(self) -> Mapping[SongId, PrepStatus]:
        """Read-only snapshot for views. Merged with party state at the read boundary (shell.views)."""
        return MappingProxyType(dict(self._board))

    async def run(self) -> None:
        """Scheduler loop, forever. Every demanded song gets a job at once; the gates enforce two
        downloads and one accelerator task at a time, in demand order."""
        probe = asyncio.create_task(self._probe())
        backfill = asyncio.create_task(self._backfill(probe))
        try:
            while True:
                await self._wake.wait()
                self._wake.clear()
                for song in sorted(self._ranks, key=self._ranks.__getitem__):
                    status = self._board.get(song)
                    if status and status.stage == "waiting" and song not in self._jobs:
                        self._jobs[song] = asyncio.create_task(self._job(self._requests[song]), name=f"prepare {song}")
        finally:
            for job in self._jobs.values():
                job.cancel()
            probe.cancel()
            backfill.cancel()
            await asyncio.gather(probe, backfill, *self._jobs.values(), return_exceptions=True)
            await self._stages.stop()

    async def _probe(self) -> None:
        self._device = await self._stages.start()
        self._changed()

    async def _backfill(self, probe: asyncio.Task[None]) -> None:
        """Advanced lyrics matching for library songs prepared before it existed (technical spec "Songs already
        in the library"). Once per song and matching version, whatever the switch says. It takes the accelerator
        only when no demanded song wants it, and one song at a time, so a queued song waits at most one song."""
        await asyncio.gather(probe, return_exceptions=True)
        records = await asyncio.to_thread(self._library.newest, 1_000_000)
        todo = [r for r in records if r.lyrics_source == "lrclib"
                and _advanced_lyrics.needs_matching(self._library.root / r.meta.id)]
        log.info("advanced lyrics matching: %d library songs to match", len(todo))
        for rec in todo:
            key = SongId(f"advanced:{rec.meta.id}")
            try:
                await self._stages.advanced_lyrics(rec.meta, SongNames(rec.artist_names, rec.alt_titles),
                                                   self._library.root / rec.meta.id,
                                                   lambda: self._accelerator.hold(key))
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("advanced lyrics matching of %s failed", rec.meta.id)

    async def _job(self, request: PrepRequest) -> None:
        song = request.song.id
        staging = self._library.staging_dir(song)
        try:
            await prepare_song(request.song, request.source, staging, self._stages,
                               lambda stage, p: self._report(song, stage, p), self._slot)
            record = await self._record(request, staging)
            await asyncio.to_thread(self._library.install, song, record)
            self._board[song] = PrepStatus("ready", 1.0)
            self._on_ready(song)
        except _Dropped:
            self._board.pop(song, None)
            if not any(staging.iterdir()):
                staging.rmdir()
        except PrepFailed as e:
            log.warning("preparation of %s failed: %s", song, e)
            self._fail(song, e.reason)
        except OSError as e:
            log.exception("preparation of %s failed", song)
            self._fail(song, "disk_full" if e.errno == errno.ENOSPC else "processing_crashed")
        except Exception:
            log.exception("preparation of %s failed", song)
            self._fail(song, "processing_crashed")
        finally:
            del self._jobs[song]
            if song not in self._ranks:
                self._board.pop(song, None)
            self._changed()

    def _fail(self, song: SongId, reason: FailReason) -> None:
        self._board[song] = PrepStatus("failed", None, reason)

    def _slot(self, resource: Resource, song: SongId) -> AbstractAsyncContextManager[None]:
        return (self._downloads if resource == "download" else self._accelerator).hold(song)

    async def _record(self, request: PrepRequest, staging_dir: Path) -> SongRecord:
        doc = LyricsDoc.model_validate_json((staging_dir / "lyrics.json").read_text("utf-8"))
        names = await self._catalog.describe(request.song)
        return SongRecord(request.song, names.artist_names, names.alt_titles, doc.language, doc.source,
                          f"https://www.youtube.com/watch?v={request.song.id}")

    def _report(self, song: SongId, stage: PrepStage, progress: float | None) -> None:
        status = PrepStatus(stage, None if progress is None else round(progress * 20) / 20)
        if self._board.get(song) != status:
            self._board[song] = status
            self._changed()

    def _changed(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._on_board_change()
            return
        if self._flush is None:
            delay = max(0.0, self._last_flush + 1 / BOARD_HZ - loop.time())
            self._flush = loop.call_later(delay, self._emit)

    def _emit(self) -> None:
        self._flush = None
        self._last_flush = asyncio.get_running_loop().time()
        self._on_board_change()
