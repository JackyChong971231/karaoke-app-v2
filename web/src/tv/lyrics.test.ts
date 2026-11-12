import { describe, expect, it } from "vitest";
import type { LyricsLine } from "../wire/types";
import { currentLine, fitLines, LINE_HOLD_S, slotLines, wordFill } from "./lyrics";

const line = (start: number, texts: string[]): LyricsLine => ({
  words: texts.map((text, i) => ({ text, start: start + i, end: start + i + 1, gapBefore: i > 0 })),
});

describe("lyrics timing", () => {
  const lines = [line(0, ["a", "b"]), line(3, ["c", "d"]), line(6, ["e"])];

  it("holds a finished line briefly before moving on", () => {
    expect(currentLine(lines, 1.5)).toBe(0);
    expect(currentLine(lines, 2 + LINE_HOLD_S - 0.01)).toBe(0);
    expect(currentLine(lines, 2 + LINE_HOLD_S + 0.01)).toBe(1);
    expect(currentLine(lines, 100)).toBe(lines.length);
  });

  it("keeps line i in slot i % 2 with the next line in the other slot", () => {
    expect(slotLines(0)).toEqual([0, 1]);
    expect(slotLines(1)).toEqual([2, 1]);
    expect(slotLines(2)).toEqual([2, 3]);
  });

  it("fills a word left to right over its own time", () => {
    const w = { text: "x", start: 2, end: 4, gapBefore: false };
    expect([wordFill(w, 1), wordFill(w, 3), wordFill(w, 5)]).toEqual([0, 0.5, 1]);
  });

  it("splits a too-wide line at a word boundary and keeps word times", () => {
    const long = line(0, ["one", "two", "three", "four"]);
    const width = (l: LyricsLine): number => l.words.reduce((n, w) => n + w.text.length, 0);
    const out = fitLines([long], width, 8);
    expect(out.map((l) => l.words.map((w) => w.text))).toEqual([["one", "two"], ["three"], ["four"]]);
    expect(out.flatMap((l) => l.words)).toEqual(long.words);
  });
});
