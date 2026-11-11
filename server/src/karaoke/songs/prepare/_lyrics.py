"""Word-timed lyrics. Private. Produces a LyricsDoc (the wire type the TV reads), so the file format
has one definition shared by the writer here and the reader on the TV.

Pure helpers (lookup parsing, script conversion, splitting, widening, line fitting) are separated from
the two calls that touch the world (LRCLIB HTTP, Accelerator), so each rule is unit-testable on
fixtures from the prototype.
"""

from __future__ import annotations

from pathlib import Path

from karaoke.core import SongMeta
from karaoke.songs.prepare._accelerator import Accelerator, AlignedLine
from karaoke.contract import LyricsDoc, LyricsLine

LINE_WIDTH_BUDGET_EM = 24.0
"""Approximate row width in em at the TV's 6vh font on a 16:9 screen at 90% width (26.7 em), minus margin.
Lines wider than this are split at preparation time; the TV shrinks the font only as a last guard."""


async def build(song: SongMeta, vocals_wav: Path, accel: Accelerator) -> LyricsDoc:
    """TODO pseudocode (technical spec 'Prepare lyrics'):
        text = await lookup_lrclib(song)                      # None -> transcribe path
        if text:
            lang = detect_language(text)                      # Hangul->ko, kana->ja, Han->zh, else en
            if lang == "zh": text = to_traditional(text)      # OpenCC s2hk
            lines, gaps = split_for_alignment(text, lang)     # CJK per character, remember gap_before
            aligned = await accel.run(Align(vocals_wav, lines, lang))
            source = "lrclib"
        else:
            aligned = await accel.run(Transcribe(vocals_wav)); convert Han text to Traditional
            source = "transcribed"                            # TV + phone show 'lyrics may be wrong'
        lines = restore_gaps(aligned, gaps)
        lines = widen_first_words(lines)
        lines = fit_lines(lines, LINE_WIDTH_BUDGET_EM)
        return LyricsDoc(version=1, source=source, language=lang, lines=lines)
    Alignment runs against the VIDEO's own audio, which removes the +4..+24 s intro offsets
    seen when timing against the album.
    """
    raise NotImplementedError


async def lookup_lrclib(song: SongMeta) -> str | None:
    """Search by title + artist (+ duration within 5 s). Prefer a result in the song's own script
    (Hangul over romanized Korean). Return plain line text, timestamps dropped. Network error -> None."""
    raise NotImplementedError


def widen_first_words(lines: list[LyricsLine]) -> list[LyricsLine]:
    """TODO pseudocode (measured fix; 18-26 lines changed per song):
        prev_end = 0
        for line: typical = median length of words[1:] (0.3 s if < 3 words)
            if first.end - first.start < 0.5 * typical: first.start = max(prev_end, first.end - typical)
            prev_end = last word end
    """
    raise NotImplementedError


def fit_lines(lines: list[LyricsLine], budget_em: float) -> list[LyricsLine]:
    """Split any line wider than budget at the word gap nearest its middle (prefer real spaces and
    punctuation, x0.7 score bonus as in the prototype), recursively. Each half keeps its word times.
    Width estimate: full-width (CJK, kana, Hangul) = 1.0 em, other characters 0.55 em."""
    raise NotImplementedError
