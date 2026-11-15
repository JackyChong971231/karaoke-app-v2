// Karaoke lyrics on the TV. Pure timing functions plus one DOM renderer driven by requestAnimationFrame.
// Not React: per-word fills update 60 times a second through a CSS variable, with no re-render.

import type { LyricsBreak, LyricsDoc, LyricsLine, LyricsWord } from "../wire/types";

/** How long a finished line stays highlighted before its slot moves on. From the prototype. */
export const LINE_HOLD_S = 0.4;
const FONT_VH = 6.2;
const MAX_WIDTH_VW = 0.88;

/** During a break the next line appears this long before it is sung. Technical spec "TV: breaks". */
export const BREAK_LEAD_S = 3;

/**
 * The intro or mid-song break being shown at display time t, with the whole seconds left until its next line.
 * Null outside breaks, in the last BREAK_LEAD_S before the next line, and for outros, which show nothing.
 */
export function activeBreak(
  breaks: readonly LyricsBreak[] | null | undefined,
  t: number,
): { kind: "intro" | "break"; secondsLeft: number } | null {
  for (const b of breaks ?? []) {
    if (b.kind === "outro") continue;
    if (t >= b.start && t < b.end - BREAK_LEAD_S) return { kind: b.kind, secondsLeft: Math.ceil(b.end - t) };
  }
  return null;
}

/** Index of the line being sung at display time t: the first line with t < end + hold. lines.length when done. */
export function currentLine(lines: readonly LyricsLine[], t: number): number {
  const i = lines.findIndex((l) => {
    const last = l.words.at(-1);
    return last === undefined || t < last.end + LINE_HOLD_S;
  });
  return i < 0 ? lines.length : i;
}

/**
 * Which line each slot shows. Line i always lives in slot i % 2. While line `cur` is sung, the other slot already
 * shows `cur + 1`; when `cur` finishes, its slot gets `cur + 2`. Slot 0 sits left, slot 1 sits lower right.
 */
export function slotLines(cur: number): [slot0: number, slot1: number] {
  return cur % 2 === 0 ? [cur, cur + 1] : [cur + 1, cur];
}

/** 0..1 fill of one word at display time t, left to right over [start, end]. */
export function wordFill(word: LyricsWord, t: number): number {
  if (t <= word.start) return 0;
  if (t >= word.end) return 1;
  return (t - word.start) / (word.end - word.start);
}

export function lineText(line: LyricsLine): string {
  return line.words.map((w, i) => (i > 0 && w.gapBefore ? " " : "") + w.text).join("");
}

/**
 * Split a line too wide for one row at the word boundary nearest its middle, keeping word times. Preparation
 * splits long lines already; this catches a narrower screen than the one preparation assumed.
 */
export function fitLines(lines: readonly LyricsLine[], width: (line: LyricsLine) => number, max: number): LyricsLine[] {
  const out: LyricsLine[] = [];
  const visit = (words: LyricsWord[]): void => {
    if (words.length < 2 || width({ words }) <= max) {
      out.push({ words });
      return;
    }
    let best = 1;
    let bestScore = Infinity;
    for (let i = 1; i < words.length; i++) {
      const left = width({ words: words.slice(0, i) });
      const right = width({ words: words.slice(i) });
      const prev = words[i - 1]?.text ?? "";
      const atGap = words[i]?.gapBefore === true || /[,，、。!?！？]$/.test(prev);
      const score = Math.abs(left - right) * (atGap ? 0.7 : 1);
      if (score < bestScore) {
        bestScore = score;
        best = i;
      }
    }
    visit(words.slice(0, best));
    visit(words.slice(best));
  };
  for (const line of lines) {
    const words = line.words.filter((w) => w.text.trim() !== "");
    if (words.length > 0) visit(words);
  }
  return out;
}

export interface LyricsProbe {
  slots: { line: number | null; text: string; fills: number[] }[];
  lineCount: number;
  breakText: string;
  version: number | null;
}

interface SlotState {
  el: HTMLElement;
  line: number | null;
  spans: HTMLSpanElement[];
  fills: number[];
}

export class LyricsRenderer {
  private doc: LyricsDoc | null = null;
  private lines: LyricsLine[] = [];
  private readonly slots: [SlotState, SlotState];
  private breakShown = "";

  constructor(els: [HTMLElement, HTMLElement], private readonly breakEl: HTMLElement) {
    this.slots = [
      { el: els[0], line: null, spans: [], fills: [] },
      { el: els[1], line: null, spans: [], fills: [] },
    ];
    // Splits and font sizes depend on the screen size, so a resized window re-fits the lines.
    addEventListener("resize", () => { this.setDoc(this.doc); });
  }

  /** Swapping docs mid-song (the advanced lyrics switch) clears both slots; the next frame redraws them for now. */
  setDoc(doc: LyricsDoc | null): void {
    if (doc === this.doc) return;
    this.doc = doc;
    this.lines = doc === null ? [] : this.fit(doc.lines);
    for (const s of this.slots) this.show(s, null);
    this.showBreak("");
  }

  get current(): LyricsDoc | null {
    return this.doc;
  }

  /** Draw for display time t (audible position plus the AV offset). */
  render(t: number): void {
    if (this.lines.length === 0) return;
    const brk = activeBreak(this.doc?.breaks, t);
    this.showBreak(brk === null ? "" : `♪ ${brk.kind === "intro" ? "Intro" : "Break"} · ${String(brk.secondsLeft)}`);
    if (brk !== null) {
      for (const s of this.slots) if (s.line !== null) this.show(s, null);
      return;
    }
    const cur = currentLine(this.lines, t);
    const wanted = slotLines(cur);
    this.slots.forEach((slot, i) => {
      const index = wanted[i] ?? null;
      const line = index === null ? undefined : this.lines[index];
      if (slot.line !== (line === undefined ? null : index)) this.show(slot, line === undefined ? null : index);
      if (line === undefined) return;
      line.words.forEach((w, j) => {
        const p = wordFill(w, t);
        if (slot.fills[j] !== p) {
          slot.fills[j] = p;
          slot.spans[j]?.style.setProperty("--p", `${(p * 100).toFixed(2)}%`);
        }
      });
    });
  }

  probe(): LyricsProbe {
    return {
      slots: this.slots.map((s) => ({ line: s.line, text: s.el.textContent ?? "", fills: [...s.fills] })),
      lineCount: this.lines.length,
      breakText: this.breakShown,
      version: this.doc?.version ?? null,
    };
  }

  private showBreak(text: string): void {
    if (text === this.breakShown) return;
    this.breakShown = text;
    this.breakEl.textContent = text;
    this.breakEl.hidden = text === "";
  }

  private show(slot: SlotState, index: number | null): void {
    slot.line = index;
    slot.el.replaceChildren();
    slot.spans = [];
    slot.fills = [];
    slot.el.style.setProperty("--size", `${String(FONT_VH)}vh`);
    const line = index === null ? undefined : this.lines[index];
    if (line === undefined) return;
    for (const [i, w] of line.words.entries()) {
      const span = document.createElement("span");
      span.className = "w";
      span.textContent = (i > 0 && w.gapBefore ? " " : "") + w.text;
      slot.el.append(span);
      slot.spans.push(span);
      slot.fills.push(0);
    }
    const max = innerWidth * MAX_WIDTH_VW;
    if (slot.el.scrollWidth > max) {
      slot.el.style.setProperty("--size", `${String((FONT_VH * max) / slot.el.scrollWidth)}vh`);
    }
  }

  private fit(lines: readonly LyricsLine[]): LyricsLine[] {
    const ctx = document.createElement("canvas").getContext("2d");
    if (ctx === null) return [...lines];
    ctx.font = `800 ${String((innerHeight * FONT_VH) / 100)}px ${getComputedStyle(this.slots[0].el).fontFamily}`;
    return fitLines(lines, (l) => ctx.measureText(lineText(l)).width, innerWidth * MAX_WIDTH_VW);
  }
}
