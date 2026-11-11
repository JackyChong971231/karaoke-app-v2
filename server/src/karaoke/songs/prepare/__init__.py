"""Preparation: turn a SongMeta into a complete library folder.

Public surface is the Preparer class and its status types. The stage code (_pipeline, _download,
_accelerator, _lyrics) is private: import-linter forbids importing it from outside this package.

The Preparer is a RECONCILER, not a job API. Callers never "start" or "cancel" a job. They declare the
full ordered list of songs they want (`set_demand`), and the Preparer works toward it. That makes every
call idempotent, makes restart recovery the same code path as normal operation, and leaves the party
reducer with nothing to remember about jobs.

States per song (the board):

    waiting --> downloading --> separating --> aligning --> ready
       ^            |               |              |
       |            +---------------+--------------+--> failed(reason)
       +-- (retry: song leaves all demand, then is demanded again)

  'waiting' = demanded but not started, or started but waiting for the accelerator.
  'ready' is reported to the party as SongReady; it is also reported immediately for songs already on disk.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from karaoke.core import SongId, SongMeta
from karaoke.songs.catalog import Catalog
from karaoke.songs.library import Library
from karaoke.vocab import FailReason, PrepStage

Lane = Literal["party", "import"]
"""Party demand always goes first. Import demand fills idle capacity (the ~468-song second import
can run during a party without ever delaying a queued song)."""

Device = Literal["cuda", "cpu"]


@dataclass(frozen=True, slots=True)
class FromYouTube:
    pass


@dataclass(frozen=True, slots=True)
class FromV1Files:
    """Importer reuse: v1 video + v1 separated stems are converted, not re-downloaded or re-separated.
    Lyrics are always redone."""

    video: Path
    instrumental: Path
    vocals: Path


Source = FromYouTube | FromV1Files


@dataclass(frozen=True, slots=True)
class PrepRequest:
    song: SongMeta
    source: Source = FromYouTube()


@dataclass(frozen=True, slots=True)
class PrepStatus:
    stage: PrepStage
    progress: float | None = None
    """0..1 within the stage when known. Quantized to 5% so views don't churn."""
    failure: FailReason | None = None


class Preparer:
    def __init__(
        self,
        library: Library,
        catalog: Catalog,
        stages: "Stages",
        on_ready: Callable[[SongId], None],
        on_board_change: Callable[[], None],
    ) -> None:
        """`stages` is the real pipeline or the harness fake (same scheduler either way).
        Callbacks are invoked on the asyncio loop thread; the shell turns on_ready into a SongReady input."""
        raise NotImplementedError

    @property
    def device(self) -> Device:
        """Probed once at boot inside the accelerator process: cuda if torch.cuda.is_available(), else cpu.
        Shown on the phone settings screen. Nothing else in the app branches on it."""
        raise NotImplementedError

    def set_demand(self, lane: Lane, wanted: Sequence[PrepRequest]) -> None:
        """Replace this lane's demand with `wanted` (ordered, most urgent first). Idempotent.

        TODO pseudocode:
            for r in wanted:
                if library.has(r.song.id): on_ready(r.song.id)   # every time: the party's `ready` is a set
                elif r.song.id not in board: board[id] = waiting
                elif board[id].stage == failed and id was absent from all demand last call: board[id] = waiting  # retry
            songs absent from all lanes and still 'waiting' are dropped from the board.
            A RUNNING job whose song left demand is NOT cancelled: it finishes and lands in the library.
            (Cheap on GPU, and it keeps the code free of cancellation paths.)
            wake the scheduler.
        """
        raise NotImplementedError

    def board(self) -> Mapping[SongId, PrepStatus]:
        """Read-only snapshot for views. Merged with party state at the read boundary (shell.views)."""
        raise NotImplementedError

    async def run(self) -> None:
        """Scheduler loop, forever.

        TODO pseudocode (capacity and priority):
            priority(song) = (lane rank, index in that lane's demand)      # recomputed at every pick
            - up to 2 downloads at once (network-bound), highest priority first
            - ONE accelerator task at a time (separate or align), highest priority among songs whose
              previous stage is done. GPU memory (8 GB) and CPU time both argue for serial.
            - each job = _pipeline.prepare(request, staging, stages); progress -> board -> on_board_change
              (throttled to 2 Hz total)
            - on success: library.install(...) ; board[id] = ready ; on_ready(id)
            - on failure: board[id] = failed(reason)
        """
        raise NotImplementedError


class Stages:
    """The three stage runners, as one injectable object. Real: _pipeline.RealStages. Harness: FakeStages
    copies fixture files after configurable delays, so the harness exercises the real scheduler,
    staging, and install. Defined as a class with NotImplemented methods; see _pipeline.py for contracts."""

    async def download(self, song: SongMeta, source: Source, into: Path, progress: Callable[[float], None]) -> None:
        raise NotImplementedError

    async def separate(self, into: Path, progress: Callable[[float], None]) -> None:
        raise NotImplementedError

    async def lyrics(self, song: SongMeta, into: Path, progress: Callable[[float], None]) -> None:
        raise NotImplementedError
