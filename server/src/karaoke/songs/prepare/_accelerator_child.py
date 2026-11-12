"""The accelerator child process: the only module that imports torch, Demucs, and stable-ts. Private.

The server never imports this module. `_accelerator.Accelerator` starts it by module path, so the
import-linter contract "torch-only-in-accelerator" holds for every module the server loads.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from multiprocessing.connection import Connection
from typing import Any

from karaoke.songs.prepare._accelerator import (
    WHISPER_MODEL, Align, AlignedLine, AlignedWord, Device, Separate, Task, Transcribe, Transcript,
)


def main(conn: Connection) -> None:
    import torch

    device: Device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        torch.set_num_threads(max(1, (os.cpu_count() or 4) - 2))
        if sys.platform == "win32":
            import ctypes
            k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            k32.SetPriorityClass(k32.GetCurrentProcess(), 0x00004000)  # BELOW_NORMAL_PRIORITY_CLASS
    conn.send(("ready", device))
    models = _Models(device)
    models.load()
    while True:
        try:
            task = conn.recv()
        except EOFError:
            return
        if task is None:
            return
        try:
            result = models.run(task, lambda p: conn.send(("progress", p)))
            conn.send(("result", result))
        except Exception as e:
            conn.send(("error", f"{type(e).__name__}: {e}"))


class _Models:
    def __init__(self, device: Device) -> None:
        self.device = device
        self._separator: Any = None
        self._whisper: Any = None

    def load(self) -> None:
        self._separator_model()
        self._model()

    def _separator_model(self) -> Any:
        if self._separator is None:
            from demucs.api import Separator
            self._separator = Separator(model="htdemucs", device=self.device, progress=False)
        return self._separator

    def run(self, task: Task, progress: Callable[[float], None]) -> Any:
        match task:
            case Separate():
                return self.separate(task, progress)
            case Align():
                return self.align(task)
            case Transcribe():
                return self.transcribe(task)

    def separate(self, task: Separate, progress: Callable[[float], None]) -> None:
        import soundfile as sf
        import torch

        separator = self._separator_model()
        last = [0.0]

        def on_chunk(info: dict[str, Any]) -> None:
            if info.get("state") == "end" and info.get("audio_length"):
                p = min(1.0, info["segment_offset"] / info["audio_length"])
                if p - last[0] >= 0.05:
                    last[0] = p
                    progress(p)

        separator.update_parameter(callback=on_chunk)
        audio, rate = sf.read(task.wav, dtype="float32", always_2d=True)
        _, stems = separator.separate_tensor(torch.from_numpy(audio.T.copy()), rate)
        vocals = stems.pop("vocals")
        instrumental = sum(stems.values())
        for name, wave in (("instrumental.wav", instrumental), ("vocals.wav", vocals)):
            part = task.out_dir / (name + ".part")
            sf.write(part, wave.clamp(-1, 1).cpu().numpy().T, separator.samplerate, subtype="PCM_16",
                     format="WAV")
            os.replace(part, task.out_dir / name)

    def _model(self) -> Any:
        if self._whisper is None:
            import stable_whisper
            self._whisper = stable_whisper.load_model(WHISPER_MODEL, device=self.device)
        return self._whisper

    def align(self, task: Align) -> tuple[AlignedLine, ...]:
        res = self._model().align(str(task.vocals_wav), task.text, language=task.language, original_split=True,
                                  verbose=None)
        if res is None:
            raise RuntimeError("alignment produced no result")
        return _lines(res)

    def transcribe(self, task: Transcribe) -> Transcript:
        res = self._model().transcribe(str(task.vocals_wav), verbose=None)
        return Transcript(str(res.language or "en"), _lines(res))


def _lines(res: Any) -> tuple[AlignedLine, ...]:
    return tuple(
        AlignedLine(tuple(AlignedWord(w.word, float(w.start), float(w.end)) for w in seg.words))
        for seg in res.segments if seg.text.strip()
    )
