"""The only place PyTorch runs: one child process holding Demucs htdemucs and Whisper `small`. Private.

Why a process and not a thread:
- A CUDA or native crash kills the child, not the server. The party keeps playing; the job retries once.
- The server's asyncio loop (WebSockets, TV clock relay) never competes with PyTorch for the GIL.
- On CPU-only laptops the child runs at BELOW_NORMAL priority with torch threads = cores - 2, so
  separation (2-3.5 min) cannot starve the browser's audio worklet on the same laptop.

GPU or CPU is decided once, here, at child start. Nothing outside reports anything but `device`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True, slots=True)
class Separate:
    wav: Path
    out_dir: Path


@dataclass(frozen=True, slots=True)
class Align:
    vocals_wav: Path
    text: str
    """Lines separated by newlines; CJK already split into single characters separated by spaces."""
    language: str
    """Whisper code. Cantonese uses 'zh' (measured: `small` + 'zh' beats `large-v3` + 'yue')."""


@dataclass(frozen=True, slots=True)
class Transcribe:
    vocals_wav: Path


Task = Separate | Align | Transcribe


@dataclass(frozen=True, slots=True)
class AlignedWord:
    text: str
    start: float
    end: float


@dataclass(frozen=True, slots=True)
class AlignedLine:
    words: tuple[AlignedWord, ...]


class Accelerator:
    """Async facade over the child process. One task at a time (the Preparer's scheduler already serializes)."""

    def __init__(self) -> None:
        raise NotImplementedError

    async def start(self) -> Literal["cuda", "cpu"]:
        """Spawn the child (multiprocessing 'spawn'), load models, return the probed device."""
        raise NotImplementedError

    async def run(self, task: Task, progress) -> tuple[AlignedLine, ...] | None:
        """Send a task; await its result.

        TODO pseudocode (crash handling):
            send task over the pipe; await result with no fixed timeout but a liveness check every 5 s
            if the child exits mid-task: restart it, re-run the task ONCE; a second crash raises
            PrepFailed('processing_crashed'). Models reload on restart (~5 s on GPU).
        """
        raise NotImplementedError
