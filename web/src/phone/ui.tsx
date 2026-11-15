// Small presentational pieces shared by the phone screens and the import page.

import type { JSX } from "react";
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { localThumbFor, thumbnailFor } from "../wire/http";
import { assertNever } from "../wire/socket";
import type { Readiness } from "../wire/types";
import { failText, stageText } from "./text";

const PATHS = {
  play: "M8 5.14v13.72a1 1 0 0 0 1.52.85l10.9-6.86a1 1 0 0 0 0-1.7L9.52 4.29A1 1 0 0 0 8 5.14Z",
  pause: "M6.5 5h4v14h-4zM13.5 5h4v14h-4z",
  skip: "M5 5.9v12.2a1 1 0 0 0 1.55.83L15 13.2V18a1 1 0 0 0 1 1h1a1 1 0 0 0 1-1V6a1 1 0 0 0-1-1h-1a1 1 0 0 0-1 1v4.8L6.55 5.07A1 1 0 0 0 5 5.9Z",
  restart: "M12 5V1L7 6l5 5V7c3.31 0 6 2.69 6 6s-2.69 6-6 6-6-2.69-6-6H4c0 4.42 3.58 8 8 8s8-3.58 8-8-3.58-8-8-8Z",
  forward: "M12 5V1l5 5-5 5V7c-3.31 0-6 2.69-6 6s2.69 6 6 6 6-2.69 6-6h2c0 4.42-3.58 8-8 8s-8-3.58-8-8 3.58-8 8-8Z",
  mic: "M12 14a3 3 0 0 0 3-3V5a3 3 0 1 0-6 0v6a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11h-2Z",
  queue: "M3 6h13v2H3zm0 5h13v2H3zm0 5h9v2H3zm15-5v6.27A3 3 0 1 0 20 20V13h2v-2h-4Z",
  search:
    "M10.5 3a7.5 7.5 0 0 1 5.96 12.05l4.25 4.24-1.42 1.42-4.24-4.25A7.5 7.5 0 1 1 10.5 3Zm0 2a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11Z",
  plus: "M11 5h2v6h6v2h-6v6h-2v-6H5v-2h6z",
  minus: "M5 11h14v2H5z",
  check: "m9.5 16.6-4.3-4.3-1.4 1.4 5.7 5.7L21.2 7.7l-1.4-1.4z",
  close: "m6.4 5 5.6 5.6L17.6 5 19 6.4 13.4 12l5.6 5.6-1.4 1.4-5.6-5.6L6.4 19 5 17.6l5.6-5.6L5 6.4z",
  back: "M15.7 5.7 14.3 4.3 6.6 12l7.7 7.7 1.4-1.4L9.4 12z",
  chevronDown: "M7.4 8.6 6 10l6 6 6-6-1.4-1.4-4.6 4.6z",
  more: "M12 7a2 2 0 1 1 0-4 2 2 0 0 1 0 4Zm0 7a2 2 0 1 1 0-4 2 2 0 0 1 0 4Zm0 7a2 2 0 1 1 0-4 2 2 0 0 1 0 4Z",
  grip: "M9 5a1.5 1.5 0 1 1 0 3 1.5 1.5 0 0 1 0-3Zm6 0a1.5 1.5 0 1 1 0 3 1.5 1.5 0 0 1 0-3ZM9 10.5a1.5 1.5 0 1 1 0 3 1.5 1.5 0 0 1 0-3Zm6 0a1.5 1.5 0 1 1 0 3 1.5 1.5 0 0 1 0-3ZM9 16a1.5 1.5 0 1 1 0 3 1.5 1.5 0 0 1 0-3Zm6 0a1.5 1.5 0 1 1 0 3 1.5 1.5 0 0 1 0-3Z",
  up: "M12 4.6 4.3 12.3l1.4 1.4L11 8.4V20h2V8.4l5.3 5.3 1.4-1.4z",
  trash: "M9 3h6l1 2h4v2H4V5h4l1-2Zm-3 6h12l-1 12H7L6 9Zm4 2v8h1.5v-8H10Zm3.5 0v8H15v-8h-1.5Z",
  alert: "M12 3 1.8 20.5h20.4L12 3Zm-1 6h2v6h-2V9Zm0 8h2v2h-2v-2Z",
  tv: "M3 5h18a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1h-7v2h3v2H7v-2h3v-2H3a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1Zm1 2v9h16V7H4Z",
  note: "M19 3v12.5a3.5 3.5 0 1 1-2-3.16V7h-7v10.5a3.5 3.5 0 1 1-2-3.16V3h11Z",
  user: "M12 12a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9Zm0 2c-4.4 0-8 2.2-8 5v2h16v-2c0-2.8-3.6-5-8-5Z",
  video: "M4 5h12a1 1 0 0 1 1 1v3.2l4-2.7v11l-4-2.7V18a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1Zm1 2v10h10V7H5Z",
  heart:
    "M12 20.3 10.6 19C5.4 14.4 2 11.3 2 7.5 2 4.4 4.4 2 7.5 2c1.7 0 3.4.8 4.5 2.1A6 6 0 0 1 16.5 2C19.6 2 22 4.4 22 7.5c0 3.8-3.4 6.9-8.6 11.5L12 20.3Zm0-2.7c4.8-4.3 8-7.2 8-10.1C20 5.5 18.5 4 16.5 4c-1.5 0-3 1-3.6 2.4h-1.8C10.5 5 9 4 7.5 4 5.5 4 4 5.5 4 7.5c0 2.9 3.2 5.8 8 10.1Z",
  heartFill:
    "M12 20.3 10.6 19C5.4 14.4 2 11.3 2 7.5 2 4.4 4.4 2 7.5 2c1.7 0 3.4.8 4.5 2.1A6 6 0 0 1 16.5 2C19.6 2 22 4.4 22 7.5c0 3.8-3.4 6.9-8.6 11.5L12 20.3Z",
  star: "m12 17.3 6.2 3.7-1.6-7 5.4-4.7-7.1-.6L12 2 9.1 8.7 2 9.3l5.4 4.7-1.6 7z",
  lyrics: "M4 5h16v2H4zm0 4h16v2H4zm0 4h16v2H4zm0 4h10v2H4z",
  external: "M14 3h7v7h-2V6.4l-8.3 8.3-1.4-1.4L17.6 5H14V3ZM5 5h6v2H5v12h12v-6h2v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2Z",
  vocalOff:
    "M12 14a3 3 0 0 0 3-3V5a3 3 0 0 0-5.82-1.03L15 9.8V11M3.3 2.9 2 4.2l7 7V11a3 3 0 0 0 4.23 2.73l1.45 1.45A5 5 0 0 1 7 11H5a7 7 0 0 0 6 6.92V21h2v-3.08a6.96 6.96 0 0 0 3.14-1.24l3.65 3.65 1.3-1.3L3.3 2.9ZM19 11h-2c0 .74-.16 1.44-.45 2.07l1.48 1.48c.6-1.04.97-2.27.97-3.55Z",
} as const;

export type IconName = keyof typeof PATHS;

export function Icon(props: { name: IconName; size?: number; className?: string }): JSX.Element {
  const size = props.size ?? 24;
  return (
    <svg
      className={`icon ${props.className ?? ""}`}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      aria-hidden="true"
      focusable="false"
    >
      <path fill="currentColor" d={PATHS[props.name]} />
    </svg>
  );
}

export function Spinner(props: { size?: number }): JSX.Element {
  const size = props.size ?? 18;
  return <span className="spinner" style={{ width: size, height: size }} role="status" aria-label="Working" />;
}

const GRADIENTS = [
  ["#8b5cf6", "#3b2a8f"],
  ["#2f7bff", "#1b3f8f"],
  ["#ec4899", "#7e1d55"],
  ["#f97316", "#8a2d0b"],
  ["#14b8a6", "#0b5a52"],
  ["#6366f1", "#2e2f8a"],
  ["#e11d48", "#6d0f27"],
  ["#0ea5e9", "#0b4a6b"],
] as const;

/** FNV-1a, so IDs that differ only in their last characters still land on different colours. */
function gradientFor(seed: string): string {
  let h = 0x811c9dc5;
  for (const ch of seed) h = Math.imul(h ^ (ch.codePointAt(0) ?? 0), 0x01000193);
  const [a, b] = GRADIENTS[(h >>> 0) % GRADIENTS.length] ?? GRADIENTS[0];
  return `linear-gradient(135deg, ${a}, ${b})`;
}

/** Song art: the YouTube still when it loads, a colour drawn from the song otherwise. Fixed size, no shift. */
/** A song's picture: the laptop's copy if the song is downloaded, else YouTube's, else the title's first letter.
 *  The letter shows only once every picture has failed, never while one is loading. */
export function Art(props: { songId?: string; src?: string; title: string; size?: "sm" | "md" | "lg" }): JSX.Element {
  const { songId, src } = props;
  const sources = src !== undefined ? [src] : songId !== undefined ? [localThumbFor(songId), thumbnailFor(songId)] : [];
  const key = sources.join(" ");
  const [at, setAt] = useState(0);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    setAt(0);
    setLoaded(false);
  }, [key]);
  const current = sources[at];
  const initial = [...props.title.trim()][0] ?? "♪";
  const next = (): void => {
    setLoaded(false);
    setAt((i) => i + 1);
  };
  return (
    <div
      className={`art art-${props.size ?? "sm"}`}
      style={{ background: gradientFor(songId ?? props.title) }}
    >
      {current === undefined && <span className="art-initial">{initial}</span>}
      {current !== undefined && (
        <img
          key={current}
          src={current}
          alt=""
          loading="lazy"
          className={loaded ? "is-loaded" : ""}
          onLoad={(e) => {
            // YouTube serves a 120x90 grey placeholder for unknown IDs instead of a 404.
            if (e.currentTarget.naturalWidth <= 120) next();
            else setLoaded(true);
          }}
          onError={next}
        />
      )}
    </div>
  );
}

export function ReadinessChip(props: { readiness: Readiness }): JSX.Element {
  const r = props.readiness;
  switch (r.kind) {
    case "ready":
      return (
        <span className="chip chip-ready" data-testid="readiness" data-state="ready">
          <span className="chip-dot" /> Ready
        </span>
      );
    case "preparing":
      return (
        <span className="chip chip-preparing" data-testid="readiness" data-state="preparing">
          <ProgressRing value={r.progress} />
          {stageText[r.stage]}
          {r.progress !== null && <span className="chip-num">{Math.round(r.progress * 100)}%</span>}
        </span>
      );
    case "failed":
      return (
        <span className="chip chip-failed" data-testid="readiness" data-state="failed">
          <Icon name="alert" size={13} /> {failText[r.reason]}
        </span>
      );
    default:
      return assertNever(r);
  }
}

function ProgressRing(props: { value: number | null }): JSX.Element {
  const r = 6;
  const c = 2 * Math.PI * r;
  return (
    <svg className={`ring ${props.value === null ? "is-spinning" : ""}`} width="16" height="16" viewBox="0 0 16 16">
      <circle cx="8" cy="8" r={r} className="ring-track" />
      <circle
        cx="8"
        cy="8"
        r={r}
        className="ring-value"
        strokeDasharray={c}
        strokeDashoffset={props.value === null ? c * 0.7 : c * (1 - props.value)}
      />
    </svg>
  );
}

/** Bottom sheet. Stays mounted while closing so it can slide out. */
export function Sheet(props: {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  children: ReactNode;
  testId?: string;
}): JSX.Element | null {
  const [mounted, setMounted] = useState(props.open);
  useEffect(() => {
    if (props.open) setMounted(true);
    else {
      const t = window.setTimeout(() => { setMounted(false); }, 260);
      return () => { window.clearTimeout(t); };
    }
    return undefined;
  }, [props.open]);
  if (!mounted) return null;
  return (
    <div className={`sheet-root ${props.open ? "is-open" : ""}`} data-testid={props.testId}>
      <div className="sheet-backdrop" onClick={props.onClose} />
      <div className="sheet" role="dialog" aria-modal="true">
        <div className="sheet-grabber" />
        {props.title !== undefined && <div className="sheet-title">{props.title}</div>}
        {props.children}
      </div>
    </div>
  );
}

/** Marquee speed and the still pause at each end, as a share of one sweep. */
const MARQUEE_PX_PER_S = 32;

/** One line of text. When it is too wide, it slides to its end and back, pausing at each end, so a long title
 *  never takes a second line. With reduced motion it stays still and ends in "…". */
export function Marquee(props: { text: string }): JSX.Element {
  const outer = useRef<HTMLSpanElement>(null);
  const inner = useRef<HTMLSpanElement>(null);
  const [shift, setShift] = useState(0);
  useLayoutEffect(() => {
    const measure = (): void => {
      const o = outer.current;
      const i = inner.current;
      if (o === null || i === null) return;
      setShift(Math.max(0, Math.ceil(i.scrollWidth - o.clientWidth)));
    };
    measure();
    const ro = new ResizeObserver(measure);
    if (outer.current !== null) ro.observe(outer.current);
    void document.fonts.ready.then(measure);
    return () => { ro.disconnect(); };
  }, [props.text]);
  // The keyframes hold still for 20% at each end, so the sweep itself gets 60% of the cycle.
  const seconds = Math.max(4, shift / MARQUEE_PX_PER_S / 0.6);
  return (
    <span
      ref={outer}
      className={`marquee ${shift > 0 ? "is-moving" : ""}`}
      style={{ "--shift": `-${String(shift)}px`, "--dur": `${seconds.toFixed(2)}s` }}
    >
      <span ref={inner} className="marquee-text">
        {props.text}
      </span>
    </span>
  );
}

/** The "Lyrics may be wrong" mark. Tapping it explains why, in a sheet. */
export function LyricsFlag(props: { look: "side" | "chip"; testId?: string }): JSX.Element {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        className={props.look === "side" ? "flag-side" : "chip chip-warn chip-button"}
        data-testid={props.testId}
        aria-haspopup="dialog"
        onClick={(e) => {
          e.stopPropagation();
          setOpen(true);
        }}
      >
        {props.look === "side" ? (
          <>
            <span className="round round-sm flag-side-icon">
              <Icon name="alert" size={20} />
            </span>
            <span className="round-label flag-side-label">
              Lyrics may
              <br />
              be wrong
            </span>
          </>
        ) : (
          <>
            <Icon name="alert" size={13} /> Lyrics may be wrong
            <span className="flag-info" aria-hidden="true">?</span>
          </>
        )}
      </button>
      <Sheet
        open={open}
        onClose={() => { setOpen(false); }}
        testId="lyrics-why"
        title={<div className="sheet-heading">Why the lyrics may be wrong</div>}
      >
        <div className="why">
          <p>No published lyrics were found for this song, so the app listened to the singing in the recording and wrote down the words it heard.</p>
          <p>Like automatic captions, it can mishear words, especially with fast singing, mixed languages, or loud music over the voice. The timing still follows the singing.</p>
          <button className="btn btn-block" data-testid="lyrics-why-close" onClick={() => { setOpen(false); }}>
            Got it
          </button>
        </div>
      </Sheet>
    </>
  );
}
