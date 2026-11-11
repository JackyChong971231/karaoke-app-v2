// Karaoke lyrics on the TV. Pure timing functions + one DOM renderer driven by requestAnimationFrame.
// Not React: per-word fills update 60 times a second through a CSS variable, no re-render.

import type { LyricsDoc, LyricsLine, LyricsWord } from "../wire/generated";

/** How long a finished line stays highlighted before its slot moves on. From the prototype. */
export const LINE_HOLD_S = 0.4;

/** Index of the line being sung at display time t: the first line with t < end + hold. lines.length when done. */
export function currentLine(lines: readonly LyricsLine[], t: number): number {
  void lines; void t;
  throw new Error("not implemented");
}

/**
 * Which line each slot shows. Line i always lives in slot i % 2. While line `cur` is sung, the other slot already
 * shows `cur + 1`; when `cur` finishes, its slot gets `cur + 2`. Slot 0 sits left, slot 1 sits lower right.
 */
export function slotLines(cur: number): [slot0: number, slot1: number] {
  // TODO: cur % 2 === 0 ? [cur, cur + 1] : [cur + 1, cur]
  void cur;
  throw new Error("not implemented");
}

/** 0..1 blue fill of one word at display time t, left to right over [start, end]. */
export function wordFill(word: LyricsWord, t: number): number {
  void word; void t;
  throw new Error("not implemented");
}

export interface LyricsProbe { slots: { line: number | null; text: string; fills: number[] }[]; flagged: boolean }

export class LyricsRenderer {
  constructor(slots: [HTMLElement, HTMLElement]) { void slots; throw new Error("not implemented"); }

  setDoc(doc: LyricsDoc | null): void { void doc; throw new Error("not implemented"); }

  /**
   * Draw for display time t (= audible + avOffset).
   * TODO pseudocode:
   *   cur = currentLine(lines, t); [a, b] = slotLines(cur)
   *   for each slot whose line index changed: rebuild spans (gapBefore -> leading space), reset font to 6vh,
   *     then the last guard: if scrollWidth > 90vw, shrink font proportionally. Never wrap (white-space: nowrap).
   *   for each word span in both slots: style --p = wordFill(word, t) * 100 + "%"
   */
  render(t: number): void { void t; throw new Error("not implemented"); }

  probe(): LyricsProbe { throw new Error("not implemented"); }
}
