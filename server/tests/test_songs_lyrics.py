from karaoke.contract import LyricsLine, LyricsWord
from karaoke.songs.prepare._accelerator import AlignedLine, AlignedWord, Transcript
from karaoke.songs.prepare._lyrics import (
    align_text, detect_language, fit_lines, line_width_em, lrc_text, pick_lrclib, restore_alignment,
    split_for_alignment, to_traditional, transcript_lines, widen_first_words,
)


def W(text: str, start: float, end: float, gap: bool = False) -> LyricsWord:
    return LyricsWord(text=text, start=start, end=end, gap_before=gap)


def texts(lines: list[LyricsLine]) -> list[str]:
    return ["".join((" " if w.gap_before else "") + w.text for w in line.words) for line in lines]


def test_language_detection_by_script() -> None:
    assert detect_language("눈,코,입 just you") == "ko"
    assert detect_language("無敵の笑顔で荒らすメディア") == "ja"
    assert detect_language("陀飛輪 誰曾經") == "zh"
    assert detect_language("Why'd you have to go") == "en"


def test_chinese_converts_to_hong_kong_traditional() -> None:
    assert to_traditional("小幸运 我听见雨滴落在青青草地") == "小幸運 我聽見雨滴落在青青草地"


def test_lrc_timestamps_and_blank_lines_are_dropped() -> None:
    assert lrc_text("[00:01.00] 第一句\n[00:02.50]\n[00:03.00][00:09.00]第二句") == "第一句\n第二句"


def test_credit_lines_and_a_leading_title_line_are_not_lyrics() -> None:
    raw = "[00:00.00]七里香-周杰倫\n[00:01.00]詞：方文山\n[00:02.00]作曲 : 周杰倫\n[00:20.00]窗外的麻雀\n[01:00.00]七里香 七里香"
    assert lrc_text(raw, ["七里香"]) == "窗外的麻雀\n七里香 七里香"


def test_cjk_splits_per_character_and_keeps_original_spaces() -> None:
    lines = split_for_alignment("我聽見 雨滴\n", "zh")
    assert lines == [[("我", False), ("聽", False), ("見", False), ("雨", True), ("滴", False)]]
    assert align_text(lines) == "我 聽 見 雨 滴"


def test_mixed_latin_inside_cjk_stays_one_word_and_punctuation_rides_along() -> None:
    assert split_for_alignment("你好，Eason 陳", "zh") == [[("你", False), ("好，", False), ("Eason", False), ("陳", True)]]
    assert split_for_alignment("Hello , world!", "en") == [[("Hello,", False), ("world!", True)]]


def test_aligned_times_land_on_our_own_tokens() -> None:
    tokens = split_for_alignment("天氣 好\n再見", "zh")
    aligned = [AlignedLine((AlignedWord(" 天", 1.0, 1.2), AlignedWord(" 气", 1.2, 1.5), AlignedWord(" 好", 1.6, 2.0))),
               AlignedLine((AlignedWord("再", 3.0, 3.3), AlignedWord("見", 3.3, 3.6)))]
    lines = restore_alignment(tokens, aligned)
    assert texts(lines) == ["天氣 好", "再見"]
    assert [(w.start, w.end) for w in lines[0].words] == [(1.0, 1.2), (1.2, 1.5), (1.6, 2.0)]


def test_tokens_the_aligner_dropped_are_interpolated_between_neighbours() -> None:
    tokens = split_for_alignment("a b c d", "en")
    aligned = [AlignedLine((AlignedWord(" a", 0.0, 1.0), AlignedWord(" d", 3.0, 4.0)))]
    words = restore_alignment(tokens, aligned)[0].words
    assert [(w.text, w.start, w.end) for w in words] == [("a", 0.0, 1.0), ("b", 1.0, 2.0), ("c", 2.0, 3.0), ("d", 3.0, 4.0)]


def test_short_first_word_is_widened_to_the_typical_length_but_not_into_the_previous_line() -> None:
    lines = [
        LyricsLine(words=[W("a", 0.0, 0.4), W("b", 0.4, 0.8), W("c", 0.8, 1.2)]),
        LyricsLine(words=[W("d", 1.95, 2.0), W("e", 2.0, 2.4), W("f", 2.4, 2.8)]),
        LyricsLine(words=[W("g", 2.85, 2.9), W("h", 2.9, 3.3), W("i", 3.3, 3.7)]),
    ]
    out = widen_first_words(lines)
    assert out[0].words[0].start == 0.0
    assert out[1].words[0].start == 1.6
    assert out[2].words[0].start == 2.8
    assert all(o.words[1:] == l.words[1:] for o, l in zip(out, lines))


def test_a_first_word_of_normal_length_is_left_alone() -> None:
    line = LyricsLine(words=[W("a", 1.0, 1.4), W("b", 1.4, 1.8), W("c", 1.8, 2.2)])
    assert widen_first_words([line]) == [line]


def test_long_line_splits_at_the_gap_nearest_its_middle_and_keeps_times() -> None:
    chars = "一二三四五六七八九十" * 2 + "一二三四五六七八九十" * 2
    words = [W(c, i, i + 0.5, gap=(i == 20)) for i, c in enumerate(chars)]
    out = fit_lines([LyricsLine(words=words)], 24.0)
    assert [len(l.words) for l in out] == [20, 20]
    assert out[1].words[0].gap_before is False
    assert out[1].words[0].start == 20
    assert all(line_width_em(l.words) <= 24.0 for l in out)


def test_short_line_and_unsplittable_line_are_untouched() -> None:
    short = LyricsLine(words=[W("hi", 0, 1)])
    huge = LyricsLine(words=[W("x" * 80, 0, 1)])
    assert fit_lines([short, huge], 24.0) == [short, huge]


def test_very_long_line_splits_recursively_until_every_piece_fits() -> None:
    words = [W(c, i, i + 1) for i, c in enumerate("字" * 70)]
    out = fit_lines([LyricsLine(words=words)], 24.0)
    assert len(out) == 4 and all(line_width_em(l.words) <= 24.0 for l in out)
    assert sum(len(l.words) for l in out) == 70


def test_lrclib_pick_prefers_the_songs_own_script_and_requires_the_title() -> None:
    hits = [
        {"trackName": "Other song", "syncedLyrics": "[00:01.00]눈 코 입"},
        {"trackName": "눈,코,입", "syncedLyrics": "[00:01.00]nun ko ip"},
        {"trackName": "눈,코,입", "plainLyrics": "눈 코 입"},
        {"trackName": "눈,코,입", "instrumental": True, "syncedLyrics": "[00:01.00]눈"},
    ]
    assert pick_lrclib(hits, ["눈,코,입"], "ko") == "눈 코 입"
    assert pick_lrclib(hits[:1], ["눈,코,입"], "ko") is None


def test_lrclib_pick_prefers_synced_lyrics_when_scripts_agree() -> None:
    hits = [{"trackName": "晴天", "plainLyrics": "plain"}, {"trackName": "晴天 (Live)", "syncedLyrics": "[00:01.00]故事的小黃花"}]
    assert pick_lrclib(hits, ["晴天"], "zh") == "故事的小黃花"


def test_transcript_becomes_traditional_single_characters_sharing_word_time() -> None:
    tr = Transcript("zh", (AlignedLine((AlignedWord(" 听见", 1.0, 2.0), AlignedWord(" 雨", 2.0, 2.5))),))
    lang, lines = transcript_lines(tr)
    assert lang == "zh"
    assert [(w.text, w.start, w.end, w.gap_before) for w in lines[0].words] == [
        ("聽", 1.0, 1.5, False), ("見", 1.5, 2.0, False), ("雨", 2.0, 2.5, True)]
