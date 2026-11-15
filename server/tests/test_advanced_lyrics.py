"""Advanced lyrics matching, steps 3 to 10, on made-up transcripts. No GPU: the aligner is faked by spreading each
clip's words over the clip, which is enough to show where every line may land."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path

from karaoke.contract import LyricsDoc, LyricsLine, LyricsWord
from karaoke.songs.prepare._accelerator import LOUDNESS_FRAME_S, AlignedLine, AlignedWord, Transcript
from karaoke.songs.prepare._advanced_lyrics import (
    Heard, IntroFix, Plan, _apply, best_chain, find_matches, heard_units, intro_fix, lyric_lines, units_of,
    voiced_stretches,
)
from karaoke.songs.prepare._lyrics import FoundLyrics, to_traditional


def found(*lines: str, times: Sequence[float | None] | None = None) -> FoundLyrics:
    return FoundLyrics("\n".join(lines), tuple(times) if times is not None else (None,) * len(lines))


def say(text: str, start: float, step: float = 0.4) -> list[Heard]:
    return [Heard(w, start + i * step, start + (i + 1) * step) for i, w in enumerate(text.lower().split())]


def loud(duration: float, *voiced: tuple[float, float]) -> list[float]:
    n = int(duration / LOUDNESS_FRAME_S)
    return [0.3 if any(a <= i * LOUDNESS_FRAME_S < b for a, b in voiced) else 0.0005 for i in range(n)]


def fake_align(p: Plan) -> list[tuple[AlignedLine, ...]]:
    out: list[tuple[AlignedLine, ...]] = []
    for g in p.clips:
        tokens = [t for i in g.lines for t, _ in p.lines[i].tokens]
        step = (g.end - g.start - 0.6) / len(tokens)
        words = [AlignedWord(t, g.start + 0.3 + k * step, g.start + 0.3 + (k + 1) * step) for k, t in enumerate(tokens)]
        out.append((AlignedLine(tuple(words)),))
    return out


def text(line: LyricsLine) -> str:
    return " ".join(w.text for w in line.words)


V1 = ("walking down the empty street tonight", "every light is fading out of sight")
CHORUS = ("hold me closer than before", "never let me go once more")
V2 = ("morning comes and you are gone", "still I hear our only song")


def test_chinese_matches_per_character_across_scripts() -> None:
    """Whisper often writes Simplified; the lyrics are converted to Traditional. Both sides compare as Traditional."""
    lyrics = found("我們說好不分離", "要一直一直在一起")
    tr = Transcript("zh", (AlignedLine((AlignedWord("大家好", 1.0, 3.0),)),
                           AlignedLine((AlignedWord("我们说好不分离", 20.0, 23.0),)),
                           AlignedLine((AlignedWord("要一直一直在一起", 24.0, 27.0),))))
    matches = find_matches(lyric_lines(lyrics, "zh"), heard_units(tr, "zh"), 4)
    assert {m.line for m in matches} == {0, 1}
    assert min(m.start for m in matches) >= 19.0
    assert "".join(t for t, _ in lyric_lines(lyrics, "zh")[0].tokens) == to_traditional("我們說好不分離")


def test_units() -> None:
    assert units_of("Don't!", "en") == ["dont"]
    assert units_of("说谎", "zh") == units_of("說謊", "zh") == units_of("説謊", "zh") == ["说", "谎"]
    assert units_of("눈,코", "ko") == ["눈", "코"]
    assert units_of("Yeah,", "ja") == ["yeah"]
    assert units_of("目を閉じればoh", "ja") == ["目", "を", "閉", "じ", "れ", "ば", "oh"]


def test_voiced_stretches_merge_short_gaps_and_drop_blips() -> None:
    v = voiced_stretches(loud(20, (1, 3), (3.5, 5), (10, 10.2)))
    assert [(round(a, 1), round(b, 1)) for a, b in v] == [(1.0, 5.0)]


# ---- with LRCLIB times: the failures found on 如果的事 (8TapprZVe80) ----

SONG = (*V1, *CHORUS, *V2, *CHORUS)
TIMES = (10.0, 13.0, 16.0, 19.0, 30.0, 33.0, 36.0, 39.0)


def chain_of(heard: list[Heard]) -> list[tuple[int, float]]:
    lines = lyric_lines(found(*SONG, times=TIMES), "en")
    return [(m.line, m.start) for m in best_chain(find_matches(lines, heard, 3), lines)]


def test_right_chorus_copy() -> None:
    """Both choruses read the same. The second one heard must be LRCLIB's second copy (36 s), not the first (16 s)."""
    heard = say(V1[0], 10.0) + say(V1[1], 13.0) + say(CHORUS[0], 16.0) + say(CHORUS[1], 19.0)
    heard += say(CHORUS[0], 36.0) + say(CHORUS[1], 39.0)
    assert [line for line, _ in chain_of(heard)] == [0, 1, 2, 3, 6, 7]


def test_whisper_repeating_a_line_in_the_instrumental_is_not_shown() -> None:
    heard = say(V1[0], 10.0) + say(V1[1], 13.0) + say(CHORUS[0], 16.0) + say(CHORUS[1], 19.0)
    heard += say(CHORUS[1], 24.5)
    heard += say(V2[0], 30.0) + say(V2[1], 33.0) + say(CHORUS[0], 36.0) + say(CHORUS[1], 39.0)
    chain = chain_of(heard)
    assert [line for line, _ in chain] == list(range(8))
    assert not any(23.0 < start < 28.0 for _, start in chain)


def test_a_shared_opening_is_not_a_match() -> None:
    lyrics = found("if you can give me what I need tonight", "if you can take me far away from here")
    heard = say("if you can give me what I need tonight", 5.0)
    matches = find_matches(lyric_lines(lyrics, "en"), heard, 3)
    assert {m.line for m in matches} == {0}


def test_a_match_is_not_stitched_from_words_heard_far_apart() -> None:
    lyrics = found("hold me closer than before tonight")
    heard = say("hold me closer", 5.0) + say("than before tonight", 20.0)
    matches = find_matches(lyric_lines(lyrics, "en"), heard, 3)
    assert all(m.end - m.start < 5.0 for m in matches)


# ---- the intro fix (technical spec "Revision: fix only the long intro") ----

INTRO_SONG = (*V1, *CHORUS, *V2)
INTRO_ALBUM = (0.0, 3.0, 6.0, 9.0, 12.0, 15.0)
"""LRCLIB's album times. In the video the singing starts at 30 s, so every line is sung at album time + 30."""


def doc_at(starts: Sequence[float]) -> LyricsDoc:
    lyric = lyric_lines(found(*INTRO_SONG, times=INTRO_ALBUM), "en")
    return LyricsDoc(version=1, source="lrclib", language="en", lines=[
        LyricsLine(words=[LyricsWord(text=t, start=round(s + 0.37 * k, 3), end=round(s + 0.37 * (k + 1), 3),
                                     gap_before=k > 0) for k, (t, _) in enumerate(ln.tokens)])
        for ln, s in zip(lyric, starts)])


def sung(*which: int) -> list[Heard]:
    return [h for i in which for h in say(INTRO_SONG[i], INTRO_ALBUM[i] + 30)]


def fix_for(current: LyricsDoc, heard: list[Heard]) -> IntroFix | None:
    return intro_fix(lyric_lines(found(*INTRO_SONG, times=INTRO_ALBUM), "en"), heard, "en", current)


class FakeAccel:
    def __init__(self, p: Plan) -> None:
        self.p = p

    async def run(self, task: object, progress: object) -> object:
        return fake_align(self.p)


def test_long_intro_is_fixed_and_the_rest_is_the_current_lyrics_unchanged() -> None:
    current = doc_at((2.0, 5.0, 36.0, 39.0, 42.0, 45.0))
    fix = fix_for(current, sung(0, 1, 2, 3, 4, 5))
    assert fix is not None and fix.cut == 2
    accel = FakeAccel(fix.plan)
    doc = asyncio.run(_apply(fix, Path("v.wav"), "en", accel, current, 60.0, lambda x: None))  # type: ignore[arg-type]
    assert doc is not None
    assert [text(ln) for ln in doc.lines] == list(INTRO_SONG)
    assert 29.0 <= doc.lines[0].words[0].start <= 31.0
    assert doc.lines[1].words[-1].end <= 36.0
    assert doc.lines[2:] == current.lines[2:]
    assert [b.kind for b in doc.breaks or []] == ["intro"]


def test_a_song_the_current_lyrics_already_time_right_gets_no_advanced_lyrics() -> None:
    assert fix_for(doc_at((30.0, 33.0, 36.0, 39.0, 42.0, 45.0)), sung(0, 1, 2, 3, 4, 5)) is None


def test_one_early_line_is_not_enough_to_move_anything() -> None:
    assert fix_for(doc_at((20.0, 33.0, 36.0, 39.0, 42.0, 45.0)), sung(0, 1, 2, 3, 4, 5)) is None


def test_whisper_hearing_too_little_means_no_advanced_lyrics() -> None:
    assert fix_for(doc_at((2.0, 5.0, 36.0, 39.0, 42.0, 45.0)), sung(0, 1)) is None


def test_lyrics_off_only_mid_song_are_left_alone() -> None:
    assert fix_for(doc_at((30.0, 33.0, 36.0, 30.5, 31.0, 31.5)), sung(0, 1, 2, 3, 4, 5)) is None
