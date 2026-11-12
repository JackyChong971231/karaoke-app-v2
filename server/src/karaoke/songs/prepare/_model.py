"""Types shared by the Preparer and the stage code. Re-exported from karaoke.songs.prepare."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from karaoke.core import SongMeta
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
    source: Source = field(default_factory=FromYouTube)


@dataclass(frozen=True, slots=True)
class PrepStatus:
    stage: PrepStage
    progress: float | None = None
    """0..1 within the stage when known. Quantized to 5% so views don't churn."""
    failure: FailReason | None = None


class PrepFailed(Exception):
    def __init__(self, reason: FailReason, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason: FailReason = reason


Progress = Callable[[float], None]


class Stages:
    """The three stage runners, as one injectable object. Real: _pipeline.RealStages. Harness: a fake that
    copies fixture files after configurable delays, so the harness exercises the real scheduler, staging,
    and install.

    Contracts (each writes <name>.part then renames, so a visible file is complete):
      download   FromYouTube: video.mp4 + audio.src.  FromV1Files: video.mp4, instrumental.opus,
                 vocals.opus, vocals.wav (the v1 stems are converted, so no separate stage runs).
      separate   audio.src -> instrumental.opus, vocals.opus, vocals.wav
      lyrics     vocals.wav -> lyrics.json (a karaoke.contract.LyricsDoc)
    Raise PrepFailed for a failure with a known reason."""

    async def start(self) -> Device:
        """Called once by Preparer.run before any stage. Returns the device the accelerator uses."""
        return "cpu"

    async def stop(self) -> None:
        return None

    async def download(self, song: SongMeta, source: Source, into: Path, progress: Progress) -> None:
        raise NotImplementedError

    async def separate(self, into: Path, progress: Progress) -> None:
        raise NotImplementedError

    async def lyrics(self, song: SongMeta, into: Path, progress: Progress) -> None:
        raise NotImplementedError
