"""Small real media for the fake world, generated with ffmpeg on first use, so the TV page plays real files.

    video-0.mp4 .. video-2.mp4   10 s solid colour, 640x360, H.264, no audio track
    instrumental.opus            10 s 440 Hz tone, stereo
    vocals.opus / vocals.wav     10 s 660 Hz tone, stereo
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from karaoke import contract as c
from karaoke.core import SongId

DURATION_S = 10.0
COLOURS = ("0xc0392b", "0x2471a3", "0x1e8449")
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


@dataclass(frozen=True, slots=True)
class Media:
    root: Path

    def video(self, song: SongId) -> Path:
        return self.root / f"video-{sum(map(ord, song)) % len(COLOURS)}.mp4"

    @property
    def instrumental(self) -> Path:
        return self.root / "instrumental.opus"

    @property
    def vocals(self) -> Path:
        return self.root / "vocals.opus"

    @property
    def vocals_wav(self) -> Path:
        return self.root / "vocals.wav"


def ensure_media(root: Path) -> Media:
    root.mkdir(parents=True, exist_ok=True)
    d = f"{DURATION_S:g}"
    jobs: dict[str, list[str]] = {
        f"video-{i}.mp4": ["-f", "lavfi", "-i", f"color=c={colour}:s=640x360:d={d}:r=25", "-an",
                           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-f", "mp4"]
        for i, colour in enumerate(COLOURS)
    }

    def tone(hz: int) -> list[str]:
        return ["-f", "lavfi", "-i", f"sine=frequency={hz}:duration={d}", "-ac", "2"]

    jobs["instrumental.opus"] = [*tone(440), "-c:a", "libopus", "-b:a", "96k", "-f", "ogg"]
    jobs["vocals.opus"] = [*tone(660), "-c:a", "libopus", "-b:a", "96k", "-f", "ogg"]
    jobs["vocals.wav"] = [*tone(660), "-f", "wav"]
    for name, args in jobs.items():
        out = root / name
        if out.exists():
            continue
        part = root / f"{name}.part"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args, str(part)],
                       check=True, creationflags=_NO_WINDOW)
        os.replace(part, out)
    return Media(root)


def _words(texts: list[str], start: float, step: float, cjk: bool = False) -> c.LyricsLine:
    return c.LyricsLine(words=[
        c.LyricsWord(text=t, start=round(start + i * step, 3), end=round(start + (i + 1) * step, 3),
                     gap_before=not cjk and i > 0)
        for i, t in enumerate(texts)
    ])


def lyrics_doc(transcribed: bool = False) -> c.LyricsDoc:
    """Known word times inside the 10 s fixtures, so a browser test can assert fills at a given audible time."""
    return c.LyricsDoc(version=1, source="transcribed" if transcribed else "lrclib", language="en", lines=[
        _words(["Sing", "along", "with", "the", "fake", "world"], 0.5, 0.5),
        _words(list("測試歌詞顯示"), 3.6, 0.4, cjk=True),
        _words(["Every", "word", "lights", "up", "in", "blue"], 6.2, 0.4),
        _words(["Last", "line", "of", "the", "song"], 8.6, 0.25),
    ])
