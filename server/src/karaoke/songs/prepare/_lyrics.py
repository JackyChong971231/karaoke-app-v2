"""Word-timed lyrics. Private. Produces a LyricsDoc (the wire type the TV reads), so the file format
has one definition shared by the writer here and the reader on the TV.

Pure helpers (lookup choice, script conversion, splitting, widening, line fitting) are separated from
the two calls that touch the world (LRCLIB HTTP, Accelerator), so each rule is unit-testable.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import statistics
import unicodedata
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

from opencc import OpenCC

from karaoke.contract import LyricsDoc, LyricsLine, LyricsWord
from karaoke.core import SongMeta
from karaoke.songs.catalog import SongNames, core_title
from karaoke.songs.library import search_key
from karaoke.songs.prepare._accelerator import Accelerator, Align, AlignedLine, TaskError, Transcribe, Transcript
from karaoke.vocab import LyricsSource

log = logging.getLogger(__name__)

LINE_WIDTH_BUDGET_EM = 24.0
"""Approximate row width in em at the TV's 6vh font on a 16:9 screen at 90% width (26.7 em), minus margin.
Lines wider than this are split at preparation time; the TV shrinks the font only as a last guard."""

LRCLIB = "https://lrclib.net/api/search"
_CJK = "぀-ヿ㐀-鿿豈-﫿"
_TOKEN = re.compile(rf"[{_CJK}]|[^\W{_CJK}]+(?:['’][^\W{_CJK}]+)*|[^\w\s]+")
_LRC_TAG = re.compile(r"^(\s*\[[^\]]*\])+")
_CREDIT = re.compile(r"^\s*(作?詞|作?词|作?曲|編曲|编曲|監製|监制|製作人?|制作人?|和聲|和声|混音|演唱|原唱|"
                     r"lyrics?|lyricist|composer|music|arranger|producer|written by)\s*[:：]", re.I)
PER_CHARACTER = ("zh", "ja")

Token = tuple[str, bool]
"""(text, gap_before)"""


# ---- script and language ----

def detect_language(text: str) -> str:
    hangul = len(re.findall(r"[가-힣]", text))
    kana = len(re.findall(r"[぀-ヿ]", text))
    han = len(re.findall(r"[㐀-鿿豈-﫿]", text))
    if hangul and hangul >= kana:
        return "ko"
    if kana:
        return "ja"
    if han:
        return "zh"
    return "en"


@lru_cache(maxsize=1)
def _s2hk() -> OpenCC:
    return OpenCC("s2hk")


def to_traditional(text: str) -> str:
    return str(_s2hk().convert(text))


# ---- LRCLIB ----

def lrc_text(lyrics: str, titles: Sequence[str] = ()) -> str:
    """Sung line text from synced or plain lyrics. Timestamps, blank lines, and credits are dropped: credit
    lines (詞：, 曲：) and a leading "title - artist" line are never sung, so the aligner squeezes them to
    zero length."""
    lines = [line for line in (_LRC_TAG.sub("", raw).strip() for raw in lyrics.splitlines()) if line]
    lines = [line for line in lines if not _CREDIT.match(line)]
    keys = [search_key(core_title(t)) for t in titles if t]
    while lines and re.search(r"[-–—]", lines[0]) and any(k and k in search_key(lines[0]) for k in keys):
        lines.pop(0)
    return "\n".join(lines)


def pick_lrclib(hits: Sequence[dict], titles: Sequence[str], want_script: str | None) -> str | None:  # type: ignore[type-arg]
    """The best hit for the song: its title must match, then the song's own script (Hangul over romanized
    Korean), then synced over plain, then LRCLIB's own order."""
    keys = {search_key(core_title(t)) for t in titles if t}

    def same_song(h: dict) -> bool:  # type: ignore[type-arg]
        k = search_key(core_title(h.get("trackName") or ""))
        return bool(k) and any(t and (t in k or k in t) for t in keys)

    usable = [h for h in hits
              if not h.get("instrumental") and (h.get("syncedLyrics") or h.get("plainLyrics")) and same_song(h)]
    if not usable:
        return None

    def rank(i: int) -> tuple[bool, bool, int]:
        h = usable[i]
        text = h.get("syncedLyrics") or h.get("plainLyrics") or ""
        return (bool(want_script) and detect_language(text) != want_script, not h.get("syncedLyrics"), i)

    best = usable[min(range(len(usable)), key=rank)]
    return lrc_text(best.get("syncedLyrics") or best.get("plainLyrics") or "", titles) or None


def _get(params: dict[str, str]) -> list[dict]:  # type: ignore[type-arg]
    req = urllib.request.Request(f"{LRCLIB}?{urllib.parse.urlencode(params)}",
                                 headers={"User-Agent": "karaoke-v2 (home karaoke app)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return list(json.load(r))


async def lookup_lrclib(titles: Sequence[str], artists: Sequence[str]) -> str | None:
    """Search by every known title and artist spelling. Network errors count as 'no lyrics'."""
    cores = list(dict.fromkeys(core_title(t) for t in titles if t))
    queries = [{"track_name": t, "artist_name": a} for t in cores for a in dict.fromkeys(artists) if a][:4]
    queries += [{"q": f"{cores[0]} {artists[0]}"}] if cores and artists else []
    script = detect_language(" ".join(cores))
    want = None if script == "en" else script
    for q in queries:
        try:
            text = pick_lrclib(await asyncio.to_thread(_get, q), cores, want)
        except Exception as e:
            log.warning("LRCLIB query %s failed: %s", q, e)
            continue
        if text:
            return text
    return None


# ---- splitting and timing ----

def _is_punct(text: str) -> bool:
    return not any(ch.isalnum() for ch in text)


def _attach_punctuation(tokens: list[Token]) -> list[Token]:
    """A punctuation-only token is not sung: it rides on the word before it (or after, at line start)."""
    out: list[Token] = []
    lead = ""
    for text, gap in tokens:
        if _is_punct(text):
            if out:
                out[-1] = (out[-1][0] + text, out[-1][1])
            else:
                lead += text
        else:
            out.append((lead + text, gap if out else False))
            lead = ""
    return out


def split_line(line: str, lang: str) -> list[Token]:
    if lang in PER_CHARACTER:
        tokens = [(m.group(), m.start() > 0 and line[m.start() - 1].isspace()) for m in _TOKEN.finditer(line)]
    else:
        tokens = [(w, True) for w in line.split()]
    return _attach_punctuation(tokens)


def split_for_alignment(text: str, lang: str) -> list[list[Token]]:
    """Chinese and Japanese become one word per character; the original spaces survive as gap_before."""
    lines = [split_line(line.strip(), lang) for line in text.splitlines() if line.strip()]
    return [line for line in lines if line]


def align_text(lines: list[list[Token]]) -> str:
    return "\n".join(" ".join(t for t, _ in line) for line in lines)


def _norm(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKC", text).casefold() if ch.isalnum())


def restore_alignment(lines: list[list[Token]], aligned: Sequence[AlignedLine]) -> list[LyricsLine]:
    """Put the aligner's times back on our own tokens, keeping our text and line breaks. Tokens the
    aligner dropped or rewrote get times interpolated between their timed neighbours."""
    flat = [(i, text, gap) for i, line in enumerate(lines) for text, gap in line]
    words = [w for line in aligned for w in line.words]
    times: list[tuple[float, float] | None] = [None] * len(flat)
    sm = SequenceMatcher(a=[_norm(t) for _, t, _ in flat], b=[_norm(w.text) for w in words], autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal" or (tag == "replace" and i2 - i1 == j2 - j1):
            for k in range(i2 - i1):
                times[i1 + k] = (words[j1 + k].start, words[j1 + k].end)
    _interpolate(times)
    out: list[list[LyricsWord]] = [[] for _ in lines]
    for (i, text, gap), t in zip(flat, times):
        start, end = t or (0.0, 0.0)
        out[i].append(LyricsWord(text=text, start=round(start, 3), end=round(max(start, end), 3), gap_before=gap))
    return [LyricsLine(words=ws) for ws in out if ws]


def _interpolate(times: list[tuple[float, float] | None]) -> None:
    i = 0
    while i < len(times):
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < len(times) and times[j] is None:
            j += 1
        prev_t = times[i - 1] if i > 0 else None
        next_t = times[j] if j < len(times) else None
        left = prev_t[1] if prev_t else (next_t[0] if next_t else 0.0)
        right = next_t[0] if next_t else left
        step = max(0.0, right - left) / (j - i)
        for k in range(i, j):
            times[k] = (left + step * (k - i), left + step * (k - i + 1))
        i = j


def transcript_lines(tr: Transcript) -> tuple[str, list[LyricsLine]]:
    """Whisper's own words, converted and split like looked-up lyrics. A multi-character CJK word shares
    its time evenly across its characters."""
    lang = "zh" if tr.language in ("zh", "yue") else tr.language
    lines = []
    for line in tr.lines:
        words: list[LyricsWord] = []
        for w in line.words:
            text = w.text.strip()
            if not text:
                continue
            gap = w.text[:1].isspace() and bool(words)
            if lang == "zh":
                text = to_traditional(text)
            pieces = split_line(text, lang) if lang in PER_CHARACTER else [(text, True)]
            span = (w.end - w.start) / max(1, len(pieces))
            for k, (piece, _) in enumerate(pieces):
                start = w.start + span * k
                words.append(LyricsWord(text=piece, start=round(start, 3), end=round(start + span, 3),
                                        gap_before=gap if k == 0 else False))
        if words:
            lines.append(LyricsLine(words=words))
    return lang, lines


def widen_first_words(lines: list[LyricsLine]) -> list[LyricsLine]:
    """The aligner starts each line's first word too late (median 0.15-0.22 s against ~0.4 s for other
    words, some zero-length), so the first two words lit up together. A first word shorter than half the
    line's typical word gets the typical length, starting no earlier than the previous line's end."""
    out = []
    prev_end = 0.0
    for line in lines:
        ws = line.words
        typical = statistics.median(w.end - w.start for w in ws[1:]) if len(ws) > 2 else 0.3
        first = ws[0]
        if first.end - first.start < 0.5 * typical:
            first = first.model_copy(update={"start": round(max(prev_end, first.end - typical), 3)})
            ws = [first, *ws[1:]]
        out.append(LyricsLine(words=list(ws)))
        prev_end = ws[-1].end
    return out


def _char_em(ch: str) -> float:
    return 1.0 if unicodedata.east_asian_width(ch) in ("W", "F") else 0.55


def line_width_em(words: Sequence[LyricsWord]) -> float:
    return sum(sum(map(_char_em, w.text)) + (0.55 if w.gap_before and i else 0.0) for i, w in enumerate(words))


def fit_lines(lines: list[LyricsLine], budget_em: float) -> list[LyricsLine]:
    """Split any line wider than budget at the word gap nearest its middle (real spaces and punctuation
    get a x0.7 distance bonus), recursively. Each half keeps its word times."""
    return [LyricsLine(words=ws) for line in lines for ws in _fit(line.words, budget_em)]


def _fit(words: list[LyricsWord], budget: float) -> list[list[LyricsWord]]:
    total = line_width_em(words)
    if len(words) < 2 or total <= budget:
        return [words]

    def score(k: int) -> float:
        natural = words[k].gap_before or _is_punct(words[k - 1].text[-1:])
        return abs(line_width_em(words[:k]) - total / 2) * (0.7 if natural else 1.0)

    k = min(range(1, len(words)), key=score)
    right = [words[k].model_copy(update={"gap_before": False}), *words[k + 1:]]
    return _fit(words[:k], budget) + _fit(right, budget)


# ---- the whole step ----

async def find_text(song: SongMeta, names: SongNames) -> str | None:
    titles = list(dict.fromkeys([song.title, *names.alt_titles]))
    artists = list(dict.fromkeys([song.artist.name, *names.artist_names]))
    return await lookup_lrclib(titles, artists)


async def build(song: SongMeta, text: str | None, vocals_wav: Path, accel: Accelerator,
                progress: Callable[[float], None]) -> LyricsDoc:
    """Technical spec 'Prepare lyrics', from the looked-up text (None: transcribe). Alignment runs against
    the video's own audio, which removes the +4..+24 s intro offsets seen when timing against the album."""
    source: LyricsSource = "transcribed"
    lines: list[LyricsLine] = []
    lang = "en"
    if text:
        lang = detect_language(text)
        if lang == "zh":
            text = to_traditional(text)
        tokens = split_for_alignment(text, lang)
        try:
            aligned = await accel.run(Align(vocals_wav, align_text(tokens), lang), progress)
            lines, source = restore_alignment(tokens, aligned), "lrclib"
        except TaskError as e:
            log.warning("alignment failed for %s, transcribing instead: %s", song.id, e)
    if source == "transcribed":
        lang, lines = transcript_lines(await accel.run(Transcribe(vocals_wav), progress))
    return LyricsDoc(version=1, source=source, language=lang,
                     lines=fit_lines(widen_first_words(lines), LINE_WIDTH_BUDGET_EM))
