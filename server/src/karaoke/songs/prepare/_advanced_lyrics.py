"""Advanced lyrics matching. Private. Technical spec "Changes for 2026-11-14: advanced lyrics matching".

The current lyrics (_lyrics.build) force-align the whole LRCLIB text against the whole vocal track, so every
word must land somewhere, in LRCLIB's order, even during an intro, a drama scene, or a talk to the crowd. This
module first listens (Whisper transcription), keeps only the places where what it heard matches a lyric line
(anchors), and then places every line between its anchors. It writes lyrics.advanced.json beside lyrics.json and
never changes it, so the whole module can be switched off or deleted.

Pure planning (`plan`) and assembling (`assemble`) are separate from the accelerator calls (`build_advanced`),
so every rule is unit-testable with made-up transcripts.
"""

from __future__ import annotations

import logging
import os
import re
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
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

ADVANCED_VERSION = 3
"""Bumped when the matching changes enough that library songs should be matched again."""
BREAK_MIN_S = 8.0
CLIP_MARGIN_S = 0.3
ANCHOR_SLACK_S = 1.0
"""How far beyond a line's anchored words its clip may reach, for words the transcript missed."""
MIN_ANCHORED = 0.3
"""Below this share of lines anchored, matching failed and the song keeps only lyrics.json."""
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
AGREE_S = 3.0
"""The current lyrics' time for an unheard line is trusted when it is this close to LRCLIB's time."""
AGREE_HEARD_S = 1.5
"""The current lyrics' time for a heard line is kept when it starts this close to where Whisper heard it."""
MIN_VOICED_SHARE = 0.3
"""An unheard line is placed only where at least this share of its time has voice."""
VOICE_SHARE = 0.6
"""Roughly the share of a line's LRCLIB time that is voice; the rest is breath and instrumental."""
VOICE_GAP_S = 1.0
"""Voiced frames closer than this form one voiced stretch."""
WALK_GAP_S = 4.0
"""Plain lyrics: unheard lines lead into, or follow, their anchor through voice no further apart than this."""
SQUEEZE = 2.5
"""A line sung this many times faster than the song's typical rate was misplaced by the aligner."""
MAX_DROPPED = 0.15
"""Leaving out more lines than this, with no break to explain it, means matching went wrong."""
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

def current_lines(lines: Sequence[Line], doc: LyricsDoc | None, lang: str) -> list[LyricsLine | None]:
    """The current lyrics' timing for each lyric line, or None where its text does not line up. fit_lines may
    have split a line in two, so pieces are joined back. Used only between anchors, where it is reliable."""
    out: list[LyricsLine | None] = []
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
            out.append(LyricsLine(words=[w.model_copy(update={"gap_before": g})
                                         for w, (_, g) in zip(words, line.tokens)], estimated=True))
            j = k
        else:
            out.append(None)
    return out


# ---- the plan ----

@dataclass(slots=True)
class Group:
    """Lines aligned together against one clip of the vocal track, or one line kept as the current lyrics timed it."""

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
    voiced: list[tuple[float, float]] = field(default_factory=list)
    anchored: int = 0

    @property
    def clips(self) -> list[Group]:
        """The groups sent to the aligner, in order."""
        return [g for g in self.groups if g.fixed is None]


@dataclass(frozen=True, slots=True)
class _Gap:
    """Unanchored lines between two chain neighbours, and what is known around them."""

    ids: list[int]
    lo: float
    hi: float
    side: str
    """'before' the first anchor, 'after' the last, or 'between'."""
    prev: Match | None
    nxt: Match | None


def expected_s(lines: Sequence[Line], ids: Sequence[int], rate: float) -> float:
    """How long these lines take: LRCLIB's own line times when it has them, else the song's typical rate."""
    total = 0.0
    for i in ids:
        here, nxt = lines[i].lrc, lines[i + 1].lrc if i + 1 < len(lines) else None
        if here is not None and nxt is not None and nxt > here:
            total += min(12.0, max(0.5, nxt - here))
        else:
            total += len(lines[i].units) * rate * 1.15
    return total


def _walk(voiced: Sequence[tuple[float, float]], lo: float, hi: float, need: float,
          backward: bool) -> tuple[float, float, float]:
    """Collect voiced stretches inside [lo, hi] from one end, while they stay close together, until they hold
    `need` seconds of voice. Returns (window start, window end, voice collected)."""
    segs = _clip_to(voiced, lo, hi)
    if backward:
        segs = segs[::-1]
    got, edge, span = 0.0, hi if backward else lo, None
    for a, b in segs:
        near = edge - b if backward else a - edge
        if near > WALK_GAP_S:
            break
        span = (a if span is None else min(span[0], a), b if span is None else max(span[1], b))
        got += b - a
        edge = a if backward else b
        if got >= need:
            break
    if span is None:
        return lo, hi, 0.0
    return (span[0], hi, got) if backward else (lo, span[1], got)


def _walk_window(voiced: Sequence[tuple[float, float]], gap: _Gap, need: float) -> tuple[float, float] | None:
    """Plain lyrics: where unheard lines are sung, judged by voice alone, or None when there is not enough voice
    for them. `need` is the lines' time; about VOICE_SHARE of it is voice."""
    lo, hi = gap.lo, gap.hi
    if hi - lo < 0.5:
        return None
    need *= VOICE_SHARE
    if sum(b - a for a, b in _clip_to(voiced, lo, hi)) < 0.5 * need:
        return None
    if gap.side == "between" and hi - lo <= 2 * need + 4:
        segs = _clip_to(voiced, lo, hi)
        return max(lo, segs[0][0] - CLIP_MARGIN_S), min(hi, segs[-1][1] + CLIP_MARGIN_S)
    walks = []
    if gap.side in ("before", "between"):
        walks.append(_walk(voiced, lo, hi, need, backward=True))
    if gap.side in ("after", "between"):
        walks.append(_walk(voiced, lo, hi, need, backward=False))
    a, b, got = max(walks, key=lambda w: min(w[2], need))
    if got < 0.5 * need:
        return None
    return max(lo, a - CLIP_MARGIN_S), min(hi, b + CLIP_MARGIN_S)


def _current_ok(p: Plan, cur: LyricsLine | None, gap: _Gap) -> bool:
    if cur is None or not cur.words:
        return False
    a, b = cur.words[0].start, cur.words[-1].end
    return gap.lo - 0.5 <= a and b <= gap.hi + 0.5 and b > a and voiced_share(p.voiced, a, b) >= MIN_VOICED_SHARE


def _predicted(lines: Sequence[Line], i: int, gap: _Gap) -> float | None:
    """LRCLIB's time for line i in this video: its album time plus the neighbouring anchors' offset,
    interpolated between them by LRCLIB time."""
    lrc = lines[i].lrc
    if lrc is None:
        return None
    o_prev = offset(gap.prev, lines) if gap.prev else None
    o_next = offset(gap.nxt, lines) if gap.nxt else None
    if o_prev is None:
        return None if o_next is None else lrc + o_next
    if o_next is None:
        return lrc + o_prev
    assert gap.prev is not None and gap.nxt is not None
    la, lb = lines[gap.prev.line].lrc, lines[gap.nxt.line].lrc
    frac = 0.5 if la is None or lb is None or lb <= la else min(1.0, max(0.0, (lrc - la) / (lb - la)))
    return lrc + o_prev + (o_next - o_prev) * frac


def _place_gap(p: Plan, gap: _Gap, current: Sequence[LyricsLine | None]) -> list[Group]:
    """Unheard lines, in order of trust:
    1. The current lyrics' time, when it sits on voice between the neighbouring anchors and agrees with LRCLIB's
       time. Measured: trusting it between anchors without LRCLIB's agreement broke 突然好想你, whose current
       lyrics drift mid-song too. For plain lyrics, it is trusted only between two anchors.
    2. LRCLIB's time, shifted by the neighbouring anchors' offsets, when the vocal track has voice there.
    3. For plain lyrics, the voice right next to the anchor.
    Otherwise the line is left out: it was not sung, as for a verse a live show skipped."""
    lines = p.lines
    if all(lines[i].lrc is None for i in gap.ids):
        if gap.side == "between" and all(_current_ok(p, current[i], gap) for i in gap.ids):
            return [_kept(current[i], i) for i in gap.ids]
        win = _walk_window(p.voiced, gap, expected_s(lines, gap.ids, p.rate))
        return [] if win is None else [Group(gap.ids, win[0], win[1], [True] * len(gap.ids))]
    out: list[Group] = []
    for i in gap.ids:
        pred = _predicted(lines, i, gap)
        cur = current[i]
        if pred is None:
            continue
        if cur is not None and _current_ok(p, cur, gap) and abs(cur.words[0].start - pred) <= AGREE_S:
            out.append(_kept(cur, i))
            continue
        s, e = max(gap.lo, pred - 1.0), min(gap.hi, pred + expected_s(lines, [i], p.rate) + 1.0)
        if e - s > 0.5 and voiced_share(p.voiced, s, e) >= MIN_VOICED_SHARE:
            out.append(Group([i], s, e, [True]))
    return out


def _kept(cur: LyricsLine | None, i: int) -> Group:
    assert cur is not None
    return Group([i], cur.words[0].start, cur.words[-1].end, [True], fixed=cur)


def plan(lines: list[Line], heard: Sequence[Heard], loud: Sequence[float], lang: str,
         current: Sequence[LyricsLine | None] | None = None) -> Plan | None:
    """Steps 3 to 7 of the technical spec: anchors, the chain of sung lines, and where every line goes.
    `current` is the current lyrics' timing per line (current_lines), evidence for lines Whisper did not hear."""
    duration = len(loud) * LOUDNESS_FRAME_S
    chain = best_chain(find_matches(lines, heard, anchor_len(lang)), lines)
    anchored = len({m.line for m in chain})
    if not lines or anchored < MIN_ANCHORED * len(lines):
        log.info("advanced lyrics: %d of %d lines anchored, below %.0f%%", anchored, len(lines), MIN_ANCHORED * 100)
        return None
    p = Plan(lines, [], typical_rate(chain), duration, voiced_stretches(loud), anchored)
    cur = list(current) if current is not None else [None] * len(lines)
    groups: list[Group] = []
    for k in range(len(chain) + 1):
        prev = chain[k - 1] if k > 0 else None
        nxt = chain[k] if k < len(chain) else None
        a = prev.line if prev else -1
        b = nxt.line if nxt else len(lines)
        if b > a + 1:
            side = "before" if prev is None else "after" if nxt is None else "between"
            gap = _Gap(list(range(a + 1, b)), max(0.0, prev.end + CLIP_MARGIN_S) if prev else 0.0,
                       min(duration, nxt.start - CLIP_MARGIN_S) if nxt else duration, side, prev, nxt)
            groups += _place_gap(p, gap, cur)
        if nxt is not None:
            kept = cur[nxt.line]
            if kept is not None and _agrees_with_heard(p, kept, nxt, prev, chain[k + 1] if k + 1 < len(chain) else None):
                groups.append(Group([nxt.line], kept.words[0].start, kept.words[-1].end, [False],
                                    fixed=LyricsLine(words=kept.words)))
                continue
            n = len(lines[nxt.line].units)
            s0 = nxt.start - nxt.first * p.rate - ANCHOR_SLACK_S
            s1 = nxt.end + (n - 1 - nxt.last) * p.rate + ANCHOR_SLACK_S
            floor = prev.end if prev else 0.0
            ceil = chain[k + 1].start if k + 1 < len(chain) else duration
            groups.append(Group([nxt.line], max(floor, s0, 0.0), min(ceil, s1, duration), [False]))
    p.groups = _merge(groups)
    return p


def _agrees_with_heard(p: Plan, cur: LyricsLine, m: Match, prev: Match | None, nxt: Match | None) -> bool:
    """The current lyrics already time this heard line right: it starts near where Whisper heard it and stays
    between its neighbours. Its word times are finer than the transcript's, so they are kept."""
    heard_start = m.start - m.first * p.rate
    a, b = cur.words[0].start, cur.words[-1].end
    return (abs(a - heard_start) <= AGREE_HEARD_S and b >= m.end - AGREE_HEARD_S
            and (prev is None or a >= prev.end - 0.5) and (nxt is None or b <= nxt.start + 0.5))


def _merge(groups: list[Group]) -> list[Group]:
    """Neighbouring clips that touch are aligned as one, which gives the aligner more context. Clips separated
    by a gap stay apart, so no line can spill across it. Lines kept from the current lyrics never merge."""
    out: list[Group] = []
    for g in groups:
        last = out[-1] if out else None
        if last is not None and last.fixed is None and g.fixed is None and g.start <= last.end + 0.05:
            out[-1] = Group(last.lines + g.lines, min(last.start, g.start), max(last.end, g.end),
                            last.estimated + g.estimated)
        else:
            out.append(g)
    return out


def acceptable(p: Plan, gaps: Sequence[LyricsBreak]) -> bool:
    """Safety net: many lines left out with no break to explain them means matching went wrong. The song then
    keeps only its current lyrics, which is better than a worse advanced version."""
    dropped = len(p.lines) - len({i for g in p.groups for i in g.lines})
    if dropped <= max(2, MAX_DROPPED * len(p.lines)) or any(b.kind == "break" for b in gaps):
        return True
    log.info("advanced lyrics: %d of %d lines left out with no break, keeping only the current lyrics",
             dropped, len(p.lines))
    return False


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
    """None when matching fails: the song then plays its current lyrics with the switch on. `current` is the
    song's lyrics.json, evidence for lines Whisper did not hear."""
    lang = detect_language(found.text)
    lines = lyric_lines(found, lang)
    if not lines:
        return None
    tr = await accel.run(Transcribe(vocals_wav, lang), lambda p: progress(0.6 * p))
    progress(0.6)
    loud = await accel.run(Loudness(vocals_wav), lambda p: None)
    p = plan(lines, heard_units(tr, lang), loud, lang, current_lines(lines, current, lang))
    if p is None:
        return None
    clips = tuple(Clip(g.start, g.end, align_text([lines[i].tokens for i in g.lines])) for g in p.clips)
    results = await accel.run(AlignClips(vocals_wav, lang, clips), lambda x: progress(0.6 + 0.4 * x))
    timed, gaps = assemble(p, results)
    if not acceptable(p, gaps):
        return None
    log.info("advanced lyrics: %d of %d lines anchored, %d clips, %d lines shown, breaks %s", p.anchored,
             len(lines), len(clips), len(timed), [(round(b.start), round(b.end), b.kind) for b in gaps])
    return LyricsDoc(version=2, source="lrclib", language=lang,
                     lines=fit_lines(widen_first_words(timed), LINE_WIDTH_BUDGET_EM), breaks=gaps)
