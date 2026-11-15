import type { JSX } from "react";
import { useEffect, useRef, useState } from "react";
import type { NowView, PhoneView } from "../wire/types";
import { FavHeart } from "./Favourites";
import { LyricsButton } from "./LyricsSites";
import { usePhone, useStore } from "./store";
import { formatKey, formatTime } from "./text";
import { Art, Icon, LyricsFlag, Marquee, ReadinessChip, Spinner } from "./ui";

const KEY_MIN = -6;
const KEY_MAX = 6;
const FORWARD_S = 5;

export function NowPlaying(props: { onFindSong: () => void }): JSX.Element {
  const { view } = usePhone();
  if (view === null) return <NowSkeleton />;
  const now = view.now;
  if (now === null) {
    return (
      <div className="empty" data-testid="now-empty">
        <div className="empty-art">
          <Icon name="mic" size={40} />
        </div>
        <h2>Nothing playing yet</h2>
        <p>Pick a song and it starts on the TV as soon as it is ready.</p>
        <button className="btn btn-primary" onClick={props.onFindSong}>
          <Icon name="search" size={20} /> Find a song
        </button>
        <UpNext view={view} />
      </div>
    );
  }
  return (
    <div className="now" data-testid="now-playing">
      <div className="now-hero">
        <Art songId={now.song.songId} title={now.song.title} size="lg" />
        <div className="now-text">
          <h1 className="now-title" data-testid="now-title">
            <Marquee text={now.song.title} />
          </h1>
          <div className="now-artist">
            <span className="now-artist-name">{now.song.artist}</span>
            {now.isFiller ? (
              <span className="now-who is-filler">Sing-along filler</span>
            ) : (
              <span className="now-who">
                <Icon name="mic" size={13} /> {now.singerName}
              </span>
            )}
          </div>
        </div>
        <div className="now-actions">
          <LyricsButton songId={now.song.songId} title={now.song.title} artist={now.song.artist} />
          <FavHeart songRef={{ kind: "song", songId: now.song.songId }} title={now.song.title} artistId={now.song.artistId} size="md" />
        </div>
      </div>
      <Progress now={now} />
      <Transport now={now} advancedLyrics={view.settings.advancedLyrics} />
      <div className="cards">
        <VocalCard level={view.settings.vocalLevel} />
        <KeyCard now={now} />
      </div>
      <UpNext view={view} />
    </div>
  );
}

function NowSkeleton(): JSX.Element {
  return (
    <div className="now">
      <div className="now-hero">
        <div className="art art-lg skeleton" />
        <div className="now-text">
          <div className="skeleton-line" style={{ width: "40%" }} />
          <div className="skeleton-line skeleton-lg" style={{ width: "80%" }} />
          <div className="skeleton-line" style={{ width: "55%" }} />
        </div>
      </div>
    </div>
  );
}

/** A drag with no movement for this long ends, so a touch the browser never finished cannot freeze the bar. */
const SEEK_DRAG_IDLE_MS = 1500;

// The progress bar works like a video player's: drag or tap it to jump there. While the finger is on it, the bar
// follows the finger and the time shows the place under it. Lifting sends one seek (the native "change" event).
// The bar is drawn every frame from the clock, outside React, so it never re-renders the page.
function Progress(props: { now: NowView }): JSX.Element {
  const store = useStore();
  const input = useRef<HTMLInputElement>(null);
  const elapsed = useRef<HTMLSpanElement>(null);
  const drag = useRef<number | null>(null);
  const idle = useRef<number | undefined>(undefined);
  const duration = props.now.song.durationS;
  useEffect(() => {
    let frame = 0;
    const draw = (): void => {
      const p = drag.current ?? store.progressS();
      const el = input.current;
      if (el) {
        if (drag.current === null) el.value = String(p ?? 0);
        const ratio = p === null || duration <= 0 ? 0 : Math.min(1, p / duration);
        el.style.setProperty("--fill", `${String(ratio * 100)}%`);
      }
      if (elapsed.current) elapsed.current.textContent = p === null ? "--:--" : formatTime(p);
      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => { cancelAnimationFrame(frame); };
  }, [store, duration]);
  useEffect(() => {
    const el = input.current;
    if (el === null) return;
    const release = (): void => {
      window.clearTimeout(idle.current);
      const to = drag.current ?? Number(el.value);
      drag.current = null;
      store.seek(to);
    };
    el.addEventListener("change", release);
    return () => {
      el.removeEventListener("change", release);
      window.clearTimeout(idle.current);
    };
  }, [store]);
  const endDrag = (): void => {
    window.clearTimeout(idle.current);
    drag.current = null;
  };
  return (
    <div className="progress">
      <input
        ref={input}
        type="range"
        className="seekbar"
        data-testid="seekbar"
        min={0}
        max={duration}
        step="any"
        defaultValue={0}
        aria-label="Song position"
        onChange={(e) => {
          drag.current = Number(e.currentTarget.value);
          window.clearTimeout(idle.current);
          idle.current = window.setTimeout(endDrag, SEEK_DRAG_IDLE_MS);
        }}
        onPointerCancel={endDrag}
        onTouchCancel={endDrag}
        onBlur={endDrag}
      />
      <div className="progress-times">
        <span ref={elapsed} data-testid="elapsed">--:--</span>
        <span>{formatTime(duration)}</span>
      </div>
    </div>
  );
}

function Transport(props: { now: NowView; advancedLyrics: boolean }): JSX.Element {
  const store = useStore();
  const { pending } = usePhone();
  const { now } = props;
  const pausing = pending.has("pause");
  const skipping = pending.has("skip");
  return (
    <div className="transport">
      <div className="transport-side">
        {now.lyricsFlagged ? (
          <LyricsFlag look="side" testId="now-lyrics-flagged" />
        ) : (
          <AdvancedLyricsSwitch on={props.advancedLyrics} />
        )}
      </div>
      <div className="transport-center">
      <button
        className="round round-sm round-ghost"
        data-testid="restart"
        aria-label="Sing again from the start"
        onClick={() => { store.seek(0); }}
      >
        <Icon name="restart" size={22} />
      </button>
      <button
        className="round round-xl"
        data-testid="pause"
        aria-label={now.paused ? "Resume" : "Pause"}
        disabled={pausing}
        onClick={() => void store.run("pause", { kind: "setPaused", playId: now.playId, paused: !now.paused })}
      >
        {pausing ? <Spinner size={28} /> : <Icon name={now.paused ? "play" : "pause"} size={34} />}
      </button>
      <button
        className="round round-sm round-ghost round-forward"
        data-testid="forward"
        aria-label="Forward 5 seconds"
        onClick={() => { store.seek((store.progressS() ?? 0) + FORWARD_S); }}
      >
        <Icon name="forward" size={22} />
        <span className="round-forward-num">5</span>
      </button>
      </div>
      <div className="transport-side">
        <button
          className="round round-sm round-ghost"
          data-testid="skip"
          aria-label="Skip song"
          disabled={skipping}
          onClick={() => void store.run("skip", { kind: "skip", playId: now.playId })}
        >
          {skipping ? <Spinner size={18} /> : <Icon name="skip" size={22} />}
        </button>
        <span className="round-label">Skip</span>
      </div>
    </div>
  );
}

// The advanced lyrics matching switch, app-wide, shown on every phone and the control page. Every song has both
// lyrics, so the TV swaps at once, mid-song too. A song flagged "Lyrics may be wrong" shows that flag here instead:
// it has no advanced lyrics, so the switch would do nothing for it.
function AdvancedLyricsSwitch(props: { on: boolean }): JSX.Element {
  const store = useStore();
  const { pending } = usePhone();
  return (
    <>
      <button
        type="button"
        role="switch"
        className="switch"
        data-testid="advanced-lyrics-toggle"
        aria-checked={props.on}
        aria-label="Advanced lyrics matching"
        disabled={pending.has("advancedLyrics")}
        onClick={() => void store.run("advancedLyrics", { kind: "setAdvancedLyrics", on: !props.on })}
      >
        <span className="switch-knob" />
      </button>
      <span className="round-label round-label-stack">
        Advanced
        <br />
        lyrics
      </span>
    </>
  );
}

/** Sends at most this often while dragging. The last value of a drag is always sent, by a trailing timer. */
const VOCAL_SEND_MS = 100;
/** A drag with no movement for this long ends, so a touch the browser never finished cannot freeze the slider. */
const VOCAL_DRAG_IDLE_MS = 1500;

// The server owns the level and the level the switch restores. This card shows the server's value except while
// this phone's finger is on the slider, and it sends only values the singer just set: ending a drag sends nothing,
// whichever way it ends (lift, cancel, scroll, blur), so a stale local value can never reach the server.
function VocalCard(props: { level: number }): JSX.Element {
  const store = useStore();
  const { pending } = usePhone();
  const [drag, setDrag] = useState<number | null>(null);
  const lastSentAt = useRef(0);
  const trailing = useRef<number | undefined>(undefined);
  const idle = useRef<number | undefined>(undefined);
  useEffect(() => () => {
    window.clearTimeout(trailing.current);
    window.clearTimeout(idle.current);
  }, []);
  const shown = drag ?? props.level;
  const send = (level: number): void => {
    lastSentAt.current = performance.now();
    void store.run(`vocal:${String(level)}`, { kind: "setVocal", level });
  };
  const endDrag = (): void => {
    window.clearTimeout(idle.current);
    setDrag(null);
  };
  const moved = (level: number): void => {
    setDrag(level);
    window.clearTimeout(trailing.current);
    const wait = VOCAL_SEND_MS - (performance.now() - lastSentAt.current);
    if (wait <= 0) send(level);
    else trailing.current = window.setTimeout(() => { send(level); }, wait);
    window.clearTimeout(idle.current);
    idle.current = window.setTimeout(endDrag, VOCAL_DRAG_IDLE_MS);
  };
  const busy = [...pending].some((p) => p.startsWith("vocal:"));
  const pct = Math.round(shown * 100);
  return (
    <div className="card">
      <div className="card-head">
        <span className="card-title">
          <Icon name={shown === 0 ? "vocalOff" : "mic"} size={18} /> Guide vocal
        </span>
        <span className="card-head-right">
          <span className="card-value" data-testid="vocal-value">
            {busy && <Spinner size={12} />} {pct === 0 ? "Off" : `${String(pct)}%`}
          </span>
          <button
            type="button"
            role="switch"
            className="switch"
            data-testid="vocal-toggle"
            aria-checked={props.level > 0}
            aria-label="Guide vocal on or off"
            disabled={pending.has("vocalSwitch")}
            onClick={() => {
              window.clearTimeout(trailing.current);
              endDrag();
              void store.run("vocalSwitch", { kind: "setVocalOn", on: props.level === 0 });
            }}
          >
            <span className="switch-knob" />
          </button>
        </span>
      </div>
      <input
        type="range"
        className="slider"
        data-testid="vocal-slider"
        min={0}
        max={100}
        step={1}
        value={pct}
        style={{ "--fill": `${String(pct)}%` }}
        aria-label="Guide vocal volume"
        onChange={(e) => { moved(Number(e.currentTarget.value) / 100); }}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onLostPointerCapture={endDrag}
        onTouchEnd={endDrag}
        onTouchCancel={endDrag}
        onBlur={endDrag}
      />
    </div>
  );
}

function KeyCard(props: { now: NowView }): JSX.Element {
  const store = useStore();
  const { pending } = usePhone();
  const { now } = props;
  // + and - send a step, not a target, so a phone that has not yet seen another phone's change cannot move the
  // key back. Reset is absolute. Steps are not blocked by a pending reply: each tap is one step.
  const setKey = (semitones: number): void =>
    void store.run("key", { kind: "setKey", playId: now.playId, semitones });
  const stepKey = (step: -1 | 1): void =>
    void store.run(`key:${String(performance.now())}`, { kind: "stepKey", playId: now.playId, step });
  const busy = pending.has("key");
  return (
    <div className="card card-key">
      <span className="card-title">
        <Icon name="note" size={18} /> Key
      </span>
      <div className="stepper stepper-key">
        <button
          className="round round-sm round-ghost"
          data-testid="key-down"
          aria-label="Lower key"
          disabled={busy || now.semitones <= KEY_MIN}
          onClick={() => { stepKey(-1); }}
        >
          <Icon name="minus" />
        </button>
        <div className="stepper-value" data-testid="key-value">
          {busy ? <Spinner size={18} /> : formatKey(now.semitones)}
        </div>
        <button
          className="round round-sm round-ghost"
          data-testid="key-up"
          aria-label="Raise key"
          disabled={busy || now.semitones >= KEY_MAX}
          onClick={() => { stepKey(1); }}
        >
          <Icon name="plus" />
        </button>
      </div>
      <span className="key-reset-slot">
        {now.semitones !== 0 && (
          <button className="link" data-testid="key-reset" disabled={busy} onClick={() => { setKey(0); }}>
            Reset
          </button>
        )}
      </span>
    </div>
  );
}

/** Up next opens to this many songs, and each "Load more" adds UP_NEXT_MORE. */
const UP_NEXT_FIRST = 3;
const UP_NEXT_MORE = 5;

// Collapsed by default so the whole page fits one phone screen: the header row still shows the next song and how
// many wait. Opening shows the first few, and "Load more" reveals more without leaving the page.
function UpNext(props: { view: PhoneView }): JSX.Element | null {
  const [open, setOpen] = useState(false);
  const [limit, setLimit] = useState(UP_NEXT_FIRST);
  const queue = props.view.queue;
  if (queue.length === 0) return null;
  const shown = open ? queue.slice(0, limit) : queue.slice(0, 1);
  const hidden = queue.length - shown.length;
  return (
    <section className={`upnext ${open ? "is-open" : ""}`} data-testid="up-next">
      <button
        className="upnext-head"
        data-testid="up-next-toggle"
        aria-expanded={open}
        onClick={() => {
          setOpen(!open);
          setLimit(UP_NEXT_FIRST);
        }}
      >
        <span className="section-title">
          Up next <span className="section-count">{queue.length}</span>
        </span>
        <span className="upnext-more">
          {!open && hidden > 0 && `+${String(hidden)} more`}
          <Icon name="chevronDown" size={20} className="upnext-chevron" />
        </span>
      </button>
      <ul className="list list-compact">
        {shown.map((e) => (
          <li key={e.entryId} className="row" data-testid="up-next-row">
            <Art songId={e.song.songId} title={e.song.title} />
            <div className="row-text">
              <div className="row-title">{e.song.title}</div>
              <div className="row-sub">
                {e.song.artist} · {e.singerName}
              </div>
            </div>
            <ReadinessChip readiness={e.readiness} />
          </li>
        ))}
      </ul>
      {open && hidden > 0 && (
        <button className="btn btn-quiet upnext-load" data-testid="up-next-more" onClick={() => { setLimit(limit + UP_NEXT_MORE); }}>
          Load more ({hidden})
        </button>
      )}
    </section>
  );
}
