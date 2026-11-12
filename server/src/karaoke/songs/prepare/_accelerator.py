"""The only place PyTorch runs: one child process holding Demucs htdemucs and Whisper `small`. Private.

Why a process and not a thread:
- A CUDA or native crash kills the child, not the server. The party keeps playing; the task retries once.
- The server's asyncio loop (WebSockets, TV clock relay) never competes with PyTorch for the GIL.
- On CPU-only laptops the child runs at BELOW_NORMAL priority with torch threads = cores - 2, so
  separation (2-3.5 min) cannot starve the browser's audio worklet on the same laptop.

GPU or CPU is decided once, here, at child start. Nothing outside reports anything but `device`.
"""

from __future__ import annotations

import asyncio
import multiprocessing as mp
import sys
from collections.abc import Callable
from dataclasses import dataclass
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any

from karaoke.songs.prepare._model import Device, PrepFailed

WHISPER_MODEL = "small"
"""Measured: `small` beat `large-v3` on 5 of 6 songs and tied on English."""


@dataclass(frozen=True, slots=True)
class Separate:
    wav: Path
    out_dir: Path
    """Receives instrumental.wav and vocals.wav."""


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


@dataclass(frozen=True, slots=True)
class Transcript:
    language: str
    lines: tuple[AlignedLine, ...]


class _ChildDied(Exception):
    pass


class TaskError(Exception):
    """The task raised inside the child (bad input, not a crash). Not retried."""


class Accelerator:
    """Async facade over the child process. One task at a time (the Preparer's scheduler already serializes)."""

    def __init__(self) -> None:
        self._proc: Any = None
        self._conn: Connection | None = None
        self._device: Device | None = None
        self._lock = asyncio.Lock()
        self._starting = asyncio.Lock()
        self._job: Any = None

    async def start(self) -> Device:
        """Spawn the child (multiprocessing 'spawn') and return the device it probed. The child then loads
        both models before taking a task, which overlaps the first download."""
        async with self._starting:
            if self._proc is not None and self._proc.is_alive():
                assert self._device
                return self._device
            return await self._spawn()

    async def _spawn(self) -> Device:
        ctx = mp.get_context("spawn")
        parent, child = ctx.Pipe()
        self._proc = ctx.Process(target=_run_child, args=(child,), name="karaoke-accelerator", daemon=True)
        self._proc.start()
        child.close()
        self._conn = parent
        self._job = _kill_with_parent(self._proc.pid)
        kind, device = await asyncio.to_thread(self._recv)
        assert kind == "ready"
        self._device = device
        return device

    async def run(self, task: Task, progress: Callable[[float], None]) -> Any:
        """Send a task and await its result. If the child dies mid-task it is restarted and the task
        re-run once; a second crash raises PrepFailed('processing_crashed')."""
        async with self._lock:
            for attempt in (1, 2):
                await self.start()
                try:
                    return await self._exchange(task, progress)
                except _ChildDied:
                    self._kill()
                    if attempt == 2:
                        raise PrepFailed("processing_crashed", f"accelerator died twice on {type(task).__name__}")
            raise AssertionError("unreachable")

    async def _exchange(self, task: Task, progress: Callable[[float], None]) -> Any:
        assert self._conn
        try:
            self._conn.send(task)
        except (OSError, EOFError) as e:
            raise _ChildDied() from e
        while True:
            kind, payload = await asyncio.to_thread(self._recv)
            if kind == "progress":
                progress(payload)
            elif kind == "result":
                return payload
            else:
                raise TaskError(payload)

    def _recv(self) -> tuple[str, Any]:
        assert self._conn
        while True:
            try:
                if self._conn.poll(1.0):
                    msg: tuple[str, Any] = self._conn.recv()
                    return msg
            except (OSError, EOFError) as e:
                raise _ChildDied() from e
            if not self._proc.is_alive():
                raise _ChildDied()

    def _kill(self) -> None:
        if self._proc is not None:
            self._proc.kill()
            self._proc.join(5)
        self._proc = None

    async def stop(self) -> None:
        if self._proc is not None and self._conn is not None:
            try:
                self._conn.send(None)
            except OSError:
                pass
            await asyncio.to_thread(self._proc.join, 10)
        self._kill()


def _kill_with_parent(pid: int) -> Any:
    """Put the child in a Windows job object that is killed when this process's handle closes, so a
    killed server never leaves an orphan holding the GPU and writing into staging."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.OpenProcess.restype = wintypes.HANDLE

    class BasicLimits(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class IoCounters(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in ("r", "w", "o", "rb", "wb", "ob")]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", IoCounters),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    job = k32.CreateJobObjectW(None, None)
    info = ExtendedLimits()
    info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))  # ExtendedLimitInformation
    handle = k32.OpenProcess(0x0001 | 0x0100, False, pid)  # PROCESS_TERMINATE | PROCESS_SET_QUOTA
    k32.AssignProcessToJobObject(job, handle)
    k32.CloseHandle(handle)
    return job


CHILD_MODULE = "karaoke.songs.prepare._accelerator_child"


def _run_child(conn: Connection) -> None:
    import importlib
    importlib.import_module(CHILD_MODULE).main(conn)
