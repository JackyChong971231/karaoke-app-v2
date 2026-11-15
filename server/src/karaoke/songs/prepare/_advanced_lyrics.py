"""Advanced lyrics matching. Private. Technical spec "Changes for 2026-11-14: advanced lyrics matching" and
"Revision: fix only the long intro".

The current lyrics (_lyrics.build) force-align the whole LRCLIB text against the whole vocal track, so every
word must land somewhere, even during a long intro: the first lines light up early, stall, and catch up. This
module listens (Whisper transcription) and fixes only that. When Whisper confidently heard the opening lines sung
later than the current lyrics show them, and then confidently agrees with the current lyrics, the opening is
aligned again from where the singing starts and the rest is copied from lyrics.json unchanged. Every other song
gets no advanced lyrics. It writes lyrics.advanced.json beside lyrics.json and never changes it, so the whole
module can be switched off or deleted.

The decision (`intro_fix`) and assembling (`assemble`) are separate from the accelerator calls
(`build_advanced`), so every rule is unit-testable with made-up transcripts.
"""

from __future__ import annotations

import logging
import os
import re
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from difflib import Match as Block
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

from opencc import OpenCC

from karaoke.contract import LyricsBreak, LyricsDoc, LyricsLine, LyricsWord
from karaoke.songs.prepare._accelerator import (
    LOUDNESS_FRAME_S, Accelerator, AlignClips, AlignedLine, Clip, Loudness, Transcribe, Transcript,
)
from karaoke.songs.prepare._lyrics import (
    _CJK, LINE_WIDTH_BUDGET_EM, FoundLyrics, Token, _norm, align_text, detect_language, fit_lines, restore_alignment,
    split_line, to_traditional, widen_first_words,
)

log = logging.getLogger(__name__)

ADVANCED_VERSION = 5
"""Bumped when the matching changes enough that library songs should be matched again."""
BREAK_MIN_S = 8.0
CLIP_MARGIN_S = 0.3
CHAR_UNITS = ("zh", "ja", "ko")
"""Languages matched per character. Korean too: Whisper's word spacing in Hangul often differs from LRCLIB's."""
MIN_COVER = 0.6
"""A match must cover this share of the line's units, so a shared opening (如果你...) is not a match."""
BLOCK_GAP_S = 2.0
"""Matched pieces of one line heard further apart than this are not one match."""
FORWARD_SKIP_PENALTY = 0.5
BACKWARD_PENALTY = 3.0
OFFSET_WEIGHT = 0.5
"""Chain cost per second that the offset from LRCLIB's times changes between neighbouring matches."""
OFFSET_CAP_S = 15.0
VOICE_GAP_S = 1.0
"""Voiced frames closer than this form one voiced stretch."""
SQUEEZE = 2.5
"""A line sung this many times faster than the song's typical rate was misplaced by the aligner."""
STRONG_COVER = 0.8
"""A strong anchor covers this share of its line's units (technical spec "Revision: fix only the long intro")."""
STRONG_OFFSET_S = 2.0
"""A strong anchor's offset from LRCLIB's time is this close to its neighbours'."""
MIN_STRONG = 0.2
"""Below this share of lines strongly anchored, Whisper heard too little to be trusted. The intro rule
itself (2 early, then 2 agreeing strong anchors) carries the confidence; this only rejects songs Whisper
barely heard."""
CONTRADICT_S = 2.0
"""The current lyrics agree with a strong anchor when they start its line this close to where it was heard."""
DEFAULT_RATE_S = 0.3


# ---- inputs ----

@dataclass(frozen=True, slots=True)
class Line:
    tokens: list[Token]
    units: list[str]
    lrc: float | None


@dataclass(frozen=True, slots=True)
class Heard:
    unit: str
    start: float
    end: float


@lru_cache(maxsize=1)
def _t2s() -> OpenCC:
    return OpenCC("t2s")


def units_of(text: str, lang: str) -> list[str]:
    """Matching units. Chinese compares as Simplified: Whisper writes either script, and the Hong Kong forms the
    display uses (説) differ from LRCLIB's Taiwan forms (說), but both fold to one Simplified character."""
    norm = _norm(str(_t2s().convert(text)) if lang == "zh" else text)
    if not norm:
        return []
    return _CHAR_OR_WORD.findall(norm) if lang in CHAR_UNITS else [norm]


_CHAR_OR_WORD = re.compile(rf"[{_CJK}가-힣]|[^{_CJK}가-힣]+")
"""In Chinese, Japanese, and Korean lyrics, each CJK character is a unit but an English word stays one unit:
letters matched one by one make false anchors out of repeated English hooks like "anytime, anywhere"."""


def lyric_lines(found: FoundLyrics, lang: str) -> list[Line]:
    out = []
    for raw, lrc in zip(found.text.splitlines(), found.times):
        text = to_traditional(raw.strip()) if lang == "zh" else raw.strip()
        tokens = split_line(text, lang)
        units = [u for t, _ in tokens for u in units_of(t, lang)]
        if tokens and units:
            out.append(Line(tokens, units, lrc))
    return out


def heard_units(tr: Transcript, lang: str) -> list[Heard]:
    """The transcript as matching units, each with its time. A word's time is shared evenly by its units."""
    out: list[Heard] = []
    for line in tr.lines:
        for w in line.words:
            for part in w.text.split():
                us = units_of(part, lang)
                step = (w.end - w.start) / max(1, len(us))
                out.extend(Heard(u, w.start + step * i, w.start + step * (i + 1)) for i, u in enumerate(us))
    return out


def anchor_len(lang: str) -> int:
    return 4 if lang in CHAR_UNITS else 3


# ---- voice ----

def voiced_stretches(loud: Sequence[float]) -> list[tuple[float, float]]:
    """Where the vocal track has a voice: frames above a level relative to the song's loud singing, merged
    across short gaps. Speech counts as voice too; anchors, not loudness, tell singing from talking."""
    if not loud:
        return []
    ordered = sorted(loud)
    threshold = max(0.004, 0.12 * ordered[int(0.95 * (len(ordered) - 1))])
    out: list[tuple[float, float]] = []
    for i, v in enumerate(loud):
        if v <= threshold:
            continue
        t0, t1 = i * LOUDNESS_FRAME_S, (i + 1) * LOUDNESS_FRAME_S
        if out and t0 - out[-1][1] < VOICE_GAP_S:
            out[-1] = (out[-1][0], t1)
        else:
            out.append((t0, t1))
    return [(a, b) for a, b in out if b - a >= 0.3]


def _clip_to(stretches: Sequence[tuple[float, float]], lo: float, hi: float) -> list[tuple[float, float]]:
    return [(max(a, lo), min(b, hi)) for a, b in stretches if b > lo and a < hi]


def voiced_share(stretches: Sequence[tuple[float, float]], lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.0
    return sum(b - a for a, b in _clip_to(stretches, lo, hi)) / (hi - lo)


# ---- anchors ----

@dataclass(frozen=True, slots=True)
class Match:
    line: int
    score: int
    first: int
    """First and last matched unit in the line."""
    last: int
    h_first: int
    """First and last matched unit in the transcript."""
    h_last: int
    start: float
    end: float


def find_matches(lines: Sequence[Line], heard: Sequence[Heard], k: int) -> list[Match]:
    """Every place a lyric line was heard: a run of at least k units in a row that agree, then the whole line
    compared against the transcript around it. The matched pieces must be heard close together, so a match is
    never stitched from words seconds apart, and must cover most of the line."""
    index: dict[tuple[str, ...], list[int]] = {}
    for p in range(len(heard) - k + 1):
        index.setdefault(tuple(h.unit for h in heard[p:p + k]), []).append(p)
    out: list[Match] = []
    for li, line in enumerate(lines):
        n = len(line.units)
        if n < k:
            continue
        implied = sorted({p - o for o in range(n - k + 1) for p in index.get(tuple(line.units[o:o + k]), ())})
        for group in _clusters(implied, max(3, n // 3)):
            lo, hi = max(0, group[0] - 2), min(len(heard), group[-1] + n + 2)
            sm = SequenceMatcher(a=line.units, b=[h.unit for h in heard[lo:hi]], autojunk=False)
            blocks = _close_together([b for b in sm.get_matching_blocks() if b.size], heard, lo)
            score = sum(b.size for b in blocks)
            if not blocks or max(b.size for b in blocks) < k or score < MIN_COVER * n:
                continue
            first, last = blocks[0], blocks[-1]
            h_first, h_last = lo + first.b, lo + last.b + last.size - 1
            out.append(Match(li, score, first.a, last.a + last.size - 1, h_first, h_last,
                             heard[h_first].start, heard[h_last].end))
    return out


def _close_together(raw: list[Block], heard: Sequence[Heard], lo: int) -> list[Block]:
    """The biggest matching run plus its neighbours, each heard within BLOCK_GAP_S of the next. A block is first
    split where its own units were heard far apart: Whisper's text can run on across a long pause."""
    blocks: list[Block] = []
    for blk in raw:
        a, b, size = blk.a, blk.b, 1
        for i in range(1, blk.size):
            if heard[lo + blk.b + i].start - heard[lo + blk.b + i - 1].end > BLOCK_GAP_S:
                blocks.append(Block(a, b, size))
                a, b, size = blk.a + i, blk.b + i, 0
            size += 1
        blocks.append(Block(a, b, size))
    if not blocks:
        return []
    start = end = max(range(len(blocks)), key=lambda i: blocks[i].size)

    def t0(b: Block) -> float:
        return heard[lo + b.b].start

    def t1(b: Block) -> float:
        return heard[lo + b.b + b.size - 1].end

    while start > 0 and t0(blocks[start]) - t1(blocks[start - 1]) <= BLOCK_GAP_S:
        start -= 1
    while end + 1 < len(blocks) and t0(blocks[end + 1]) - t1(blocks[end]) <= BLOCK_GAP_S:
        end += 1
    return blocks[start:end + 1]


def _clusters(values: Sequence[int], gap: int) -> list[list[int]]:
    out: list[list[int]] = []
    for v in values:
        if out and v - out[-1][-1] <= gap:
            out[-1].append(v)
        else:
            out.append([v])
    return out


def offset(m: Match, lines: Sequence[Line]) -> float | None:
    """How much later than LRCLIB's album time this line was heard. None for plain lyrics."""
    lrc = lines[m.line].lrc
    return None if lrc is None else m.start - m.first * DEFAULT_RATE_S - lrc


def best_chain(matches: Sequence[Match], lines: Sequence[Line]) -> list[Match]:
    """The chain of matches, in time order, with the best total score.

    - Following LRCLIB's order is free; a forward skip costs a little; a repeat or a jump back costs more.
    - With LRCLIB times, a change of offset between neighbouring matches costs OFFSET_WEIGHT per second, up to
      OFFSET_CAP_S. That picks the right copy of a repeated chorus (the wrong copy is a minute away), and drops a
      line Whisper invented by repeating itself during an instrumental (it jumps away and back). An inserted
      drama scene shifts the offset once and pays once."""
    ms = sorted(matches, key=lambda m: (m.h_first, m.line))
    offs = [offset(m, lines) for m in ms]
    best: list[float] = []
    prev: list[int | None] = []
    for i, m in enumerate(ms):
        score, came = float(m.score), None
        for j in range(i):
            if ms[j].h_last >= m.h_first:
                continue
            a, b = ms[j].line, m.line
            pen = 0.0 if b == a + 1 else FORWARD_SKIP_PENALTY if b > a else BACKWARD_PENALTY
            oj, oi = offs[j], offs[i]
            if oj is not None and oi is not None:
                pen += OFFSET_WEIGHT * min(abs(oi - oj), OFFSET_CAP_S)
            if best[j] - pen + m.score > score:
                score, came = best[j] - pen + m.score, j
        best.append(score)
        prev.append(came)
    if not ms:
        return []
    at: int | None = max(range(len(ms)), key=best.__getitem__)
    chain = []
    while at is not None:
        chain.append(ms[at])
        at = prev[at]
    return chain[::-1]


def typical_rate(matches: Sequence[Match]) -> float:
    """Median seconds per unit while singing, from the anchored lines."""
    rates = [(m.end - m.start) / (m.last - m.first) for m in matches if m.last > m.first and m.end > m.start]
    return statistics.median(rates) if rates else DEFAULT_RATE_S


# ---- the current lyrics, as evidence ----

def _current_spans(lines: Sequence[Line], doc: LyricsDoc | None,
                   lang: str) -> list[tuple[LyricsLine | None, int | None]]:
    """The current lyrics' timing for each lyric line, and the index in doc.lines where it starts; (None, None)
    where its text does not line up. fit_lines may have split a line in two, so pieces are joined back."""
    out: list[tuple[LyricsLine | None, int | None]] = []
    docs = doc.lines if doc else []
    j = 0
    for line in lines:
        got: list[str] = []
        words: list[LyricsWord] = []
        k = j
        while k < len(docs) and len(got) < len(line.units):
            for w in docs[k].words:
                got += units_of(w.text, lang)
                words.append(w)
            k += 1
        if got == line.units and len(words) == len(line.tokens):
            out.append((LyricsLine(words=[w.model_copy(update={"gap_before": g})
                                          for w, (_, g) in zip(words, line.tokens)], estimated=True), j))
            j = k
        else:
            out.append((None, None))
    return out


# ---- the intro fix ----

@dataclass(frozen=True, slots=True)
class IntroFix:
    """The opening lines (before `cut`) re-timed by `plan`; doc.lines from `doc_from` on are copied unchanged."""

    plan: Plan
    cut: int
    doc_from: int


def strong_anchors(chain: Sequence[Match], lines: Sequence[Line]) -> list[Match]:
    """Matches Whisper is confident about (revision step 1): most of the line heard, and the offset from
    LRCLIB's time in line with the neighbouring matches."""
    offs = [offset(m, lines) for m in chain]
    out = []
    for i, m in enumerate(chain):
        o = offs[i]
        near = [x for x in offs[max(0, i - 2):i] + offs[i + 1:i + 3] if x is not None]
        if (o is None or not near or m.score < STRONG_COVER * len(lines[m.line].units)
                or abs(o - statistics.median(near)) > STRONG_OFFSET_S):
            continue
        out.append(m)
    return out


def intro_fix(lines: list[Line], heard: Sequence[Heard], lang: str, doc: LyricsDoc) -> IntroFix | None:
    """Revision steps 1 to 6: None unless Whisper confidently shows that the current lyrics start the song too
    early. Every other song keeps exactly its current lyrics."""
    chain = best_chain(find_matches(lines, heard, anchor_len(lang)), lines)
    strong = strong_anchors(chain, lines)
    if not lines or len({m.line for m in strong}) < MIN_STRONG * len(lines):
        log.info("advanced lyrics: %d of %d lines strongly anchored, below %.0f%%",
                 len({m.line for m in strong}), len(lines), MIN_STRONG * 100)
        return None
    spans = _current_spans(lines, doc, lang)
    rate = typical_rate(chain)

    def verdict(m: Match) -> str | None:
        cur = spans[m.line][0]
        if cur is None:
            return None
        d = cur.words[0].start - (m.start - m.first * rate)
        return "agree" if abs(d) <= CONTRADICT_S else "early" if d < 0 else "late"

    verdicts = [verdict(m) for m in strong]
    at = next((k for k in range(len(strong) - 1) if verdicts[k] == verdicts[k + 1] == "agree"), None)
    if at is None:
        log.info("advanced lyrics: Whisper never agrees with the current lyrics twice in a row")
        return None
    before = verdicts[:at]
    if len(before) < 2 or any(v != "early" for v in before):
        log.info("advanced lyrics: no long intro to fix (%s before the agreement point)", before)
        return None
    cut = strong[at].line
    cur_cut, doc_from = spans[cut]
    if cur_cut is None or doc_from is None:
        return None
    until = cur_cut.words[0].start - CLIP_MARGIN_S
    start = _singing_starts(lines, strong[:at], rate)
    if until - start < 1.0:
        return None
    return IntroFix(Plan(lines[:cut], [Group(list(range(cut)), start, until, [False] * cut)], rate, until), cut, doc_from)


def _singing_starts(lines: Sequence[Line], early: Sequence[Match], rate: float) -> float:
    """Where the opening's clip starts: where Whisper heard the first early line begin, or, for opening lines
    before it, LRCLIB's time shifted by the early anchors' offset. Never later than that first heard line."""
    first = early[0]
    heard_at = first.start - first.first * rate
    offs = [o for o in (offset(m, lines) for m in early) if o is not None]
    lrc0 = lines[0].lrc
    at = heard_at if first.line == 0 or lrc0 is None or not offs else min(heard_at, lrc0 + statistics.median(offs))
    return max(0.0, at - 1.0)


# ---- the plan ----

@dataclass(slots=True)
class Group:
    """Lines aligned together against one clip of the vocal track, or one line kept as the current lyrics timed it.
    The intro fix makes a single clip: the opening lines, from where the singing starts."""

    lines: list[int]
    start: float
    end: float
    estimated: list[bool]
    fixed: LyricsLine | None = None


@dataclass(slots=True)
class Plan:
    lines: list[Line]
    groups: list[Group]
    rate: float
    duration: float

    @property
    def clips(self) -> list[Group]:
        """The groups sent to the aligner, in order."""
        return [g for g in self.groups if g.fixed is None]


# ---- assembling the result ----

def _spread(line: Line, start: float, end: float) -> LyricsLine:
    step = max(0.05, (end - start) / max(1, len(line.tokens)))
    return LyricsLine(words=[LyricsWord(text=t, start=round(start + step * i, 3), end=round(start + step * (i + 1), 3),
                                        gap_before=gap) for i, (t, gap) in enumerate(line.tokens)], estimated=True)


def assemble(p: Plan, results: Sequence[tuple[AlignedLine, ...] | None]) -> tuple[list[LyricsLine], list[LyricsBreak]]:
    """Steps 8 and 9: put the clip alignments (one per Plan.clips) back on our own words, check each line, and
    find the breaks."""
    out: list[LyricsLine] = []
    clip_results = iter(results)
    for g in p.groups:
        if g.fixed is not None:
            out.append(g.fixed)
            continue
        res = next(clip_results, None)
        tokens = [p.lines[i].tokens for i in g.lines]
        timed = restore_alignment(tokens, res) if res else []
        if len(timed) != len(g.lines) or not any(w.end > 0 for ln in timed for w in ln.words):
            out.extend(_even(p, g))
            continue
        for i, est, ln in zip(g.lines, g.estimated, timed):
            out.append(_checked(p, i, LyricsLine(words=ln.words, estimated=est or None), g))
    out = _monotonic(out)
    return out, breaks(out, p.duration)


def _even(p: Plan, g: Group) -> list[LyricsLine]:
    """A clip the aligner could not place: its lines share the clip by their length."""
    sizes = [len(p.lines[i].units) for i in g.lines]
    total, t, out = sum(sizes), g.start, []
    for i, n in zip(g.lines, sizes):
        d = (g.end - g.start) * n / max(1, total)
        out.append(_spread(p.lines[i], t, t + d))
        t += d
    return out


def _checked(p: Plan, i: int, line: LyricsLine, g: Group) -> LyricsLine:
    """A line squeezed much faster than the song's typical singing was misplaced: spread it at the typical rate."""
    words = line.words
    span = words[-1].end - words[0].start
    want = len(p.lines[i].units) * p.rate
    if span * SQUEEZE >= want:
        return line
    start = min(words[0].start, max(g.start, g.end - want))
    return _spread(p.lines[i], start, min(g.end, start + want))


def _monotonic(lines: list[LyricsLine]) -> list[LyricsLine]:
    """Clip margins may overlap by a fraction of a second: no word starts before the previous line ends."""
    out, floor = [], 0.0
    for ln in lines:
        ws = []
        for w in ln.words:
            s = max(w.start, floor)
            ws.append(w.model_copy(update={"start": round(s, 3), "end": round(max(s, w.end), 3)}))
        floor = ws[-1].end if ws else floor
        out.append(LyricsLine(words=ws, estimated=ln.estimated))
    return out


def breaks(lines: Sequence[LyricsLine], duration: float) -> list[LyricsBreak]:
    out = []
    starts = [ln.words[0].start for ln in lines if ln.words]
    ends = [ln.words[-1].end for ln in lines if ln.words]
    if not starts:
        return []
    if starts[0] >= BREAK_MIN_S:
        out.append(LyricsBreak(start=0.0, end=starts[0], kind="intro"))
    for e, s in zip(ends, starts[1:]):
        if s - e >= BREAK_MIN_S:
            out.append(LyricsBreak(start=e, end=s, kind="break"))
    if duration - ends[-1] >= BREAK_MIN_S:
        out.append(LyricsBreak(start=ends[-1], end=duration, kind="outro"))
    return out


# ---- the whole step ----

TRIED = "lyrics.advanced.tried"


def mark_tried(folder: Path) -> None:
    part = folder / (TRIED + ".part")
    part.write_text(str(ADVANCED_VERSION), "utf-8")
    os.replace(part, folder / TRIED)


def needs_matching(folder: Path) -> bool:
    """True for a song that has never been through this version of advanced lyrics matching."""
    try:
        return int((folder / TRIED).read_text("utf-8").strip()) < ADVANCED_VERSION
    except (OSError, ValueError):
        return True


async def build_advanced(found: FoundLyrics, vocals_wav: Path, accel: Accelerator,
                         progress: Callable[[float], None], current: LyricsDoc | None = None) -> LyricsDoc | None:
    """The current lyrics with only a long intro fixed (technical spec "Revision: fix only the long intro").
    None for every song that does not need that fix, or when Whisper cannot be trusted: the song then plays its
    current lyrics with the switch on."""
    if current is None:
        return None
    lang = detect_language(found.text)
    lines = lyric_lines(found, lang)
    if not lines:
        return None
    tr = await accel.run(Transcribe(vocals_wav, lang), lambda p: progress(0.6 * p))
    progress(0.6)
    loud = await accel.run(Loudness(vocals_wav), lambda p: None)
    fix = intro_fix(lines, heard_units(tr, lang), lang, current)
    if fix is None:
        return None
    return await _apply(fix, vocals_wav, lang, accel, current, len(loud) * LOUDNESS_FRAME_S,
                        lambda x: progress(0.6 + 0.4 * x))


async def _apply(fix: IntroFix, vocals_wav: Path, lang: str, accel: Accelerator, current: LyricsDoc,
                 duration: float, progress: Callable[[float], None]) -> LyricsDoc | None:
    p = fix.plan
    clips = tuple(Clip(g.start, g.end, align_text([p.lines[i].tokens for i in g.lines])) for g in p.clips)
    results = await accel.run(AlignClips(vocals_wav, lang, clips), progress)
    opening, _ = assemble(p, results)
    if len(opening) != fix.cut:
        return None
    rest = current.lines[fix.doc_from:]
    lines = fit_lines(widen_first_words(opening), LINE_WIDTH_BUDGET_EM) + rest
    intro = [b for b in breaks(lines, duration) if b.kind == "intro"]
    log.info("advanced lyrics: re-timed the first %d lines, first line %.1fs -> %.1fs", fix.cut,
             current.lines[0].words[0].start, lines[0].words[0].start)
    return current.model_copy(update={"version": 2, "lines": lines, "breaks": intro})
