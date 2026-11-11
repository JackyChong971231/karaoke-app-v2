"""One song's preparation, crash-safe and resumable. Private to karaoke.songs.prepare.

Staging layout (<library>/.staging/<video id>/):
    audio.src           downloaded audio (any container)            } stage "download"
    video.mp4           <= 1080p, audio stripped                    }
    instrumental.opus   160 kbit/s                                  } stage "separate"
    vocals.opus                                                     }
    vocals.wav          kept for alignment, deleted before install  }
    lyrics.json         LyricsDoc                                   } stage "lyrics"
    download.done / separate.done / lyrics.done   stage markers (empty files)

Crash-safety rules:
1. Every output is written as <name>.part then os.replace'd to <name>. A visible <name> is complete.
2. A stage writes its marker only after all its outputs exist. A stage with a marker is skipped.
3. Staging is keyed by song id, not attempt, so a retry after a crash or restart resumes at the first
   unmarked stage. On CPU that saves up to 3 minutes per interrupted song.
4. install() is the only exit from staging, and it is one directory rename.
Running a stage twice is therefore harmless: it overwrites its own .part files.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from karaoke.core import SongMeta
from karaoke.songs.prepare import FromV1Files, Source, Stages
from karaoke.vocab import PrepStage


async def prepare(song: SongMeta, source: Source, staging: Path, stages: Stages,
                  report: Callable[[PrepStage, float | None], None]) -> None:
    """Run the missing stages in order. Raises PrepFailed(reason) on a final failure.

    TODO pseudocode:
        if not (staging/"download.done").exists():
            report("downloading", 0); await stages.download(song, source, staging, p -> report("downloading", p))
            touch download.done
            if source is FromV1Files: touch separate.done   # stems were converted during 'download'
        if not separate.done:
            report("separating", None)   # None until the accelerator actually starts it
            await stages.separate(staging, ...); touch separate.done
        if not lyrics.done:
            report("aligning", None); await stages.lyrics(song, staging, ...); touch lyrics.done
        delete vocals.wav, audio.src
    """
    raise NotImplementedError


class PrepFailed(Exception):
    def __init__(self, reason: str) -> None:
        raise NotImplementedError


class RealStages(Stages):
    """Wires the stage contracts to yt-dlp (_download), Demucs + stable-ts (_accelerator), LRCLIB (_lyrics)."""

    async def download(self, song, source, into, progress):
        """FromYouTube: audio and video in parallel through Downloader (update + retry once).
        FromV1Files: ffmpeg strip-audio copy of the v1 video; encode v1 stems to opus; vocals.wav for alignment."""
        raise NotImplementedError

    async def separate(self, into, progress):
        """audio.src -> 44.1 kHz wav -> Accelerator.separate (htdemucs) -> instrumental/vocals wav -> opus 160k."""
        raise NotImplementedError

    async def lyrics(self, song, into, progress):
        """_lyrics.build(song, vocals.wav, accelerator) -> lyrics.json."""
        raise NotImplementedError
