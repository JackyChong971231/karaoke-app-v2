"""Compare the current lyrics with advanced lyrics matching on real library songs. Not a pytest test: it needs
the GPU, LRCLIB, and a real library. Writes nothing into the library.

    uv run python tests/lyrics_eval/run_eval.py [--library DIR] [--out DIR] [song id ...]

For each song it prints, for both versions:
- lrc<=1s: share of lines starting within 1 s of LRCLIB's time, after removing the one constant offset that fits
  best. LRCLIB is timed against the album, so this is a reference, not ground truth (as in "Measured results").
- first: when the first line lights up, and when LRCLIB (shifted by that offset) says it is sung.
- quiet: seconds of lit words while the vocal track is silent.
- the advanced breaks.
With --out, both lyrics files land in DIR/<song id>/ for a closer look.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

from karaoke.contract import LyricsDoc
from karaoke.songs.catalog import SongNames
from karaoke.songs.library import SongRecord
from karaoke.songs.prepare._accelerator import Accelerator, Loudness
from karaoke.songs.prepare._advanced_lyrics import build_advanced, voiced_share, voiced_stretches
from karaoke.songs.prepare._lyrics import FoundLyrics, _norm, detect_language, find_text, to_traditional
from karaoke.songs.prepare._pipeline import ffmpeg


def _key(text: str, lang: str) -> str:
    return _norm(to_traditional(text) if lang == "zh" else text)


def lrc_fit(doc: LyricsDoc, found: FoundLyrics) -> tuple[float, float, float | None]:
    """(share within 1 s, offset, LRCLIB first line time + offset). Doc lines are matched to LRCLIB lines in
    order by text: a doc line may be the first piece of a long line that fit_lines split."""
    lang = detect_language(found.text)
    lrc = [(_key(t, lang), s) for t, s in zip(found.text.splitlines(), found.times) if s is not None]
    if not lrc:
        return float("nan"), 0.0, None
    pairs = []
    j = 0
    for ln in doc.lines:
        text = _key("".join(w.text for w in ln.words), lang)
        if not text:
            continue
        for k in range(j, min(len(lrc), j + 6)):
            if lrc[k][0].startswith(text) and len(text) * 2 >= len(lrc[k][0]):
                pairs.append((ln.words[0].start, lrc[k][1]))
                j = k + 1
                break
    if not pairs:
        return float("nan"), 0.0, None
    offset = statistics.median(a - b for a, b in pairs)
    ok = sum(abs(a - b - offset) <= 1.0 for a, b in pairs) / len(pairs)
    return ok, offset, lrc[0][1] + offset


def quiet_lit(doc: LyricsDoc, stretches: list[tuple[float, float]]) -> float:
    total = 0.0
    for ln in doc.lines:
        a, b = ln.words[0].start, ln.words[-1].end
        total += (b - a) * (1 - voiced_share(stretches, a, b)) if b > a else 0.0
    return total


async def one(accel: Accelerator, song_dir: Path, out: Path | None) -> None:
    rec = SongRecord.from_json(json.loads((song_dir / "song.json").read_text("utf-8")))
    current = LyricsDoc.model_validate_json((song_dir / "lyrics.json").read_text("utf-8"))
    if current.source != "lrclib":
        print(f"{rec.meta.id} {rec.meta.title}: transcribed lyrics, skipped")
        return
    found = await find_text(rec.meta, SongNames(rec.artist_names, rec.alt_titles))
    if found is None:
        print(f"{rec.meta.id} {rec.meta.title}: LRCLIB has nothing now, skipped")
        return
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "vocals.wav"
        await ffmpeg("-i", song_dir / "vocals.opus", "-ac", "2", "-ar", "44100", "-f", "wav", wav)
        t = time.monotonic()
        adv = await build_advanced(found, wav, accel, lambda p: None, current)
        took = time.monotonic() - t
        stretches = voiced_stretches(await accel.run(Loudness(wav), lambda p: None))
    row = [f"{rec.meta.id} {rec.meta.title[:24]:<24} {took:5.1f}s"]
    for name, doc in (("current", current), ("advanced", adv)):
        if doc is None:
            row.append(f"{name}: none (matching failed)")
            continue
        ok, offset, lrc_first = lrc_fit(doc, found)
        first = doc.lines[0].words[0].start if doc.lines else float("nan")
        lf = "-" if lrc_first is None else f"{lrc_first:5.1f}"
        row.append(f"{name}: lrc<=1s {ok:4.0%} first {first:5.1f} (lrc {lf}) quiet {quiet_lit(doc, stretches):5.1f}s"
                   f" lines {len(doc.lines)}")
    if adv is not None and adv.breaks:
        row.append("breaks " + ", ".join(f"{b.kind} {b.start:.0f}-{b.end:.0f}" for b in adv.breaks))
    print("\n    ".join(row), flush=True)
    if out is not None:
        d = out / rec.meta.id
        d.mkdir(parents=True, exist_ok=True)
        (d / "lyrics.json").write_text(current.model_dump_json(by_alias=True, exclude_none=True, indent=1), "utf-8")
        if adv is not None:
            (d / "lyrics.advanced.json").write_text(adv.model_dump_json(by_alias=True, exclude_none=True, indent=1),
                                                    "utf-8")


async def main() -> None:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Karaoke" / "library"
    ap = argparse.ArgumentParser()
    ap.add_argument("--library", type=Path, default=base)
    ap.add_argument("--out", type=Path)
    ap.add_argument("songs", nargs="*")
    args = ap.parse_args()
    dirs = [args.library / s for s in args.songs] if args.songs else sorted(
        d for d in args.library.iterdir() if (d / "song.json").exists())
    accel = Accelerator()
    print("device", await accel.start(), flush=True)
    try:
        for d in dirs:
            try:
                await one(accel, d, args.out)
            except Exception as e:
                print(f"{d.name}: failed: {type(e).__name__}: {e}", flush=True)
    finally:
        await accel.stop()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    asyncio.run(main())
