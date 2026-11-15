"""Advanced lyrics matching, steps 3 to 10, on made-up transcripts. No GPU: the aligner is faked by spreading each
clip's words over the clip, which is enough to show where every line may land."""

from __future__ import annotations

from collections.abc import Sequence

from karaoke.contract import LyricsDoc, LyricsLine, LyricsWord
from karaoke.songs.prepare._accelerator import LOUDNESS_FRAME_S, AlignedLine, AlignedWord, Transcript
from karaoke.songs.prepare._advanced_lyrics import (
    Heard, Plan, acceptable, assemble, current_lines, find_matches, heard_units, lyric_lines, plan, units_of,
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


def run(f: FoundLyrics, heard: list[Heard], volume: list[float], lang: str = "en") -> tuple[list[LyricsLine], Plan]:
    p = plan(lyric_lines(f, lang), heard, volume, lang)
    assert p is not None
    lines, _ = assemble(p, fake_align(p))
    return lines, p


def text(line: LyricsLine) -> str:
    return " ".join(w.text for w in line.words)


V1 = ("walking down the empty street tonight", "every light is fading out of sight")
CHORUS = ("hold me closer than before", "never let me go once more")
V2 = ("morning comes and you are gone", "still I hear our only song")


def test_intro_speech_gets_no_lyrics() -> None:
    """The user's case: someone talks for 15 s, the song starts at 20 s. Today the first lines light up at 0 s."""
    heard = say("hello everyone thank you for coming tonight this one is for you", 1.0, 1.0)
    heard += say(V1[0], 20.0) + say(V1[1], 23.0) + say(CHORUS[0], 26.0) + say(CHORUS[1], 29.0)
    lines, p = run(found(*V1, *CHORUS), heard, loud(40, (1, 15), (20, 32)))
    assert [text(ln) for ln in lines] == [*V1, *CHORUS]
    assert lines[0].words[0].start >= 19.0
    _, gaps = assemble(p, fake_align(p))
    assert gaps[0].kind == "intro" and gaps[0].end >= 19.0


def test_unheard_first_line_stays_next_to_the_singing_not_on_the_talk() -> None:
    """The first line was not transcribed, so it has no anchor. It must still lead into the anchored singing,
    not spread back over the talking in the intro."""
    heard = say("good evening and welcome to the show everybody", 1.0, 1.0)
    heard += say(V1[1], 23.0) + say(CHORUS[0], 26.0) + say(CHORUS[1], 29.0)
    lines, _ = run(found(*V1, *CHORUS), heard, loud(40, (1, 10), (20, 32)))
    assert text(lines[0]) == V1[0]
    assert lines[0].estimated is True
    assert 19.0 <= lines[0].words[0].start < 23.0


def test_unheard_first_line_with_no_voice_never_takes_the_talking_intro() -> None:
    heard = say("good evening and welcome to the show everybody", 1.0, 1.0)
    heard += say(V1[1], 23.0) + say(CHORUS[0], 26.0) + say(CHORUS[1], 29.0)
    lines, _ = run(found(*V1, *CHORUS), heard, loud(40, (1, 10), (23, 32)))
    assert [text(ln) for ln in lines] == [V1[1], *CHORUS]
    assert lines[0].words[0].start >= 22.0


def test_live_show_repeats_the_chorus_and_skips_the_second_verse() -> None:
    heard = say(V1[0], 5.0) + say(V1[1], 8.0)
    for start in (11.0, 17.0, 23.0):
        heard += say(CHORUS[0], start) + say(CHORUS[1], start + 3.0)
    lines, _ = run(found(*V1, *CHORUS, *V2, *CHORUS), heard, loud(32, (5, 29)))
    assert [text(ln) for ln in lines] == [*V1, *CHORUS, *CHORUS, *CHORUS]


def test_drama_scene_mid_song_is_a_break() -> None:
    heard = say(V1[0], 5.0) + say(V1[1], 8.0)
    heard += say("where were you last night I waited for hours", 15.0, 1.5)
    heard += say(V2[0], 45.0) + say(V2[1], 48.0)
    lines, p = run(found(*V1, *V2), heard, loud(60, (5, 11), (15, 38), (45, 51)))
    assert [text(ln) for ln in lines] == [*V1, *V2]
    for ln in lines:
        assert not 12.0 < ln.words[0].start < 44.0
    _, gaps = assemble(p, fake_align(p))
    assert any(g.kind == "break" and g.start <= 12.0 and g.end >= 44.0 for g in gaps)


def test_crowd_sung_line_is_guessed_where_there_is_voice() -> None:
    """The second chorus line was sung by the crowd: not transcribed, but the vocal track has voice there."""
    heard = say(V1[0], 5.0) + say(V1[1], 8.0) + say(CHORUS[0], 11.0) + say(V2[0], 18.0) + say(V2[1], 21.0)
    lines, _ = run(found(*V1, *CHORUS, *V2), heard, loud(30, (5, 24)))
    assert [text(ln) for ln in lines] == [*V1, *CHORUS, *V2]
    guessed = lines[3]
    assert guessed.estimated is True
    assert 13.0 <= guessed.words[0].start < 18.0


def test_unsung_lines_with_no_voice_are_left_out() -> None:
    heard = say(V1[0], 5.0) + say(V1[1], 8.0) + say(CHORUS[0], 40.0) + say(CHORUS[1], 43.0)
    lines, _ = run(found(*V1, *V2, *CHORUS), heard, loud(50, (5, 11), (40, 46)))
    assert [text(ln) for ln in lines] == [*V1, *CHORUS]


def test_too_few_anchors_means_no_advanced_lyrics() -> None:
    heard = say("something else entirely was heard here", 5.0)
    assert plan(lyric_lines(found(*V1, *CHORUS, *V2), "en"), heard, loud(30, (5, 10)), "en") is None


def test_chinese_matches_per_character_across_scripts() -> None:
    """Whisper often writes Simplified; the lyrics are converted to Traditional. Both sides compare as Traditional."""
    lyrics = found("我們說好不分離", "要一直一直在一起")
    tr = Transcript("zh", (AlignedLine((AlignedWord("大家好", 1.0, 3.0),)),
                           AlignedLine((AlignedWord("我们说好不分离", 20.0, 23.0),)),
                           AlignedLine((AlignedWord("要一直一直在一起", 24.0, 27.0),))))
    p = plan(lyric_lines(lyrics, "zh"), heard_units(tr, "zh"), loud(30, (1, 3), (20, 27)), "zh")
    assert p is not None
    lines, _ = assemble(p, fake_align(p))
    assert "".join(w.text for w in lines[0].words) == to_traditional("我們說好不分離")
    assert lines[0].words[0].start >= 19.0


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


def test_unheard_opening_verse_is_placed_by_lrclib_time_not_dropped() -> None:
    """Whisper heard nothing of the first verse, sung between breaths 3 s apart. LRCLIB's times, shifted by the
    first anchor's offset, put it back where the vocal track has voice."""
    heard = say(CHORUS[0], 26.0) + say(CHORUS[1], 29.0)
    lines, _ = run(found(*V1, *CHORUS, times=(10.0, 13.0, 16.0, 19.0)), heard,
                   loud(40, (20, 22.5), (23.2, 25.0), (26, 32)))
    assert [text(ln) for ln in lines] == [*V1, *CHORUS]
    assert 19.0 <= lines[0].words[0].start < 21.0


def test_right_chorus_copy_and_unheard_second_verse() -> None:
    """Both choruses read the same. The second one heard must be LRCLIB's second copy (36 s), not the first
    (16 s), so the unheard second verse between them is placed instead of dropped."""
    heard = say(V1[0], 10.0) + say(V1[1], 13.0) + say(CHORUS[0], 16.0) + say(CHORUS[1], 19.0)
    heard += say(CHORUS[0], 36.0) + say(CHORUS[1], 39.0)
    lines, _ = run(found(*SONG, times=TIMES), heard, loud(45, (10, 22), (30, 42)))
    assert [text(ln) for ln in lines] == list(SONG)
    assert 29.0 <= lines[4].words[0].start < 31.5


def test_whisper_repeating_a_line_in_the_instrumental_is_not_shown() -> None:
    heard = say(V1[0], 10.0) + say(V1[1], 13.0) + say(CHORUS[0], 16.0) + say(CHORUS[1], 19.0)
    heard += say(CHORUS[1], 24.5)
    heard += say(V2[0], 30.0) + say(V2[1], 33.0) + say(CHORUS[0], 36.0) + say(CHORUS[1], 39.0)
    lines, _ = run(found(*SONG, times=TIMES), heard, loud(45, (10, 22), (24, 27), (30, 42)))
    assert [text(ln) for ln in lines] == list(SONG)
    assert not any(23.0 < ln.words[0].start < 28.0 for ln in lines)


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


def test_unheard_line_keeps_the_current_lyrics_timing_when_it_agrees_with_lrclib() -> None:
    heard = say(V1[0], 10.0) + say(CHORUS[0], 16.0) + say(CHORUS[1], 19.0)
    f = found(*V1, *CHORUS, times=(10.0, 13.0, 16.0, 19.0))
    lyric = lyric_lines(f, "en")
    current = LyricsDoc(version=1, source="lrclib", language="en", lines=[
        LyricsLine(words=[LyricsWord(text=t, start=13.2 + 0.3 * k, end=13.5 + 0.3 * k, gap_before=k > 0)
                          for k, (t, _) in enumerate(ln.tokens)]) for ln in lyric])
    p = plan(lyric, heard, loud(25, (10, 22)), "en", current_lines(lyric, current, "en"))
    assert p is not None
    lines, _ = assemble(p, fake_align(p))
    assert text(lines[1]) == V1[1]
    assert lines[1].words[0].start == 13.2


def test_many_lines_left_out_with_no_break_keeps_only_the_current_lyrics() -> None:
    heard = say(V1[0], 10.0) + say(V1[1], 13.0) + say(CHORUS[0], 16.0) + say(CHORUS[1], 19.0)
    p = plan(lyric_lines(found(*V1, *CHORUS, *V2, *V2, *V2), "en"), heard, loud(25, (10, 22)), "en")
    assert p is not None
    _, gaps = assemble(p, fake_align(p))
    assert not acceptable(p, gaps)


def test_heard_line_keeps_the_current_lyrics_word_times_when_they_agree() -> None:
    """Where the current lyrics already time a heard line right, its finer word times are kept as they are."""
    heard = say(V1[0], 10.0) + say(V1[1], 13.0)
    lyric = lyric_lines(found(*V1, times=(10.0, 13.0)), "en")
    current = LyricsDoc(version=1, source="lrclib", language="en", lines=[
        LyricsLine(words=[LyricsWord(text=t, start=s + 0.37 * k, end=s + 0.37 * (k + 1), gap_before=k > 0)
                          for k, (t, _) in enumerate(ln.tokens)]) for ln, s in zip(lyric, (10.2, 13.1))])
    p = plan(lyric, heard, loud(20, (10, 16)), "en", current_lines(lyric, current, "en"))
    assert p is not None and p.clips == []
    lines, _ = assemble(p, [])
    assert [ln.words[0].start for ln in lines] == [10.2, 13.1]
    assert lines[0].estimated is None
