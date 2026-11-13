import type { JSX } from "react";
import { useEffect, useRef, useState } from "react";
import type { NowView, PhoneView } from "../wire/types";
import { usePhone, useStore } from "./store";
import { formatKey, formatTime } from "./text";
import { Art, Icon, ReadinessChip, Spinner } from "./ui";

const KEY_MIN = -6;
const KEY_MAX = 6;

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
          <div className="now-eyebrow">
            {now.isFiller ? (
              <span className="tag tag-filler">Sing-along filler</span>
            ) : (
              <span className="tag tag-singer">
                <Icon name="mic" size={14} /> {now.singerName}
              </span>
            )}
            {now.lyricsFlagged && (
              <span className="tag tag-warn" data-testid="now-lyrics-flagged">
                <Icon name="alert" size={13} /> Lyrics may be wrong
              </span>
            )}
          </div>
          <h1 className="now-title" data-testid="now-title">
            {now.song.title}
          </h1>
          <div className="now-artist">{now.song.artist}</div>
        </div>
      </div>
      <Progress now={now} />
      <Transport now={now} />
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

function Progress(props: { now: NowView }): JSX.Element {
  const store = useStore();
  const bar = useRef<HTMLDivElement>(null);
  const elapsed = useRef<HTMLSpanElement>(null);
  const duration = props.now.song.durationS;
  useEffect(() => {
    let frame = 0;
    const draw = (): void => {
      const p = store.progressS();
      const ratio = p === null || duration <= 0 ? 0 : Math.min(1, p / duration);
      if (bar.current) bar.current.style.transform = `scaleX(${String(ratio)})`;
      if (elapsed.current) elapsed.current.textContent = p === null ? "--:--" : formatTime(p);
      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => { cancelAnimationFrame(frame); };
  }, [store, duration]);
  return (
    <div className="progress">
      <div className="progress-track">
        <div className="progress-fill" ref={bar} />
      </div>
      <div className="progress-times">
        <span ref={elapsed}>--:--</span>
        <span>{formatTime(duration)}</span>
      </div>
    </div>
  );
}

function Transport(props: { now: NowView }): JSX.Element {
  const store = useStore();
  const { pending } = usePhone();
  const { now } = props;
  const pausing = pending.has("pause");
  const skipping = pending.has("skip");
  return (
    <div className="transport">
      <div className="transport-side" />
      <button
        className="round round-xl"
        data-testid="pause"
        aria-label={now.paused ? "Resume" : "Pause"}
        disabled={pausing}
        onClick={() => void store.run("pause", { kind: "setPaused", playId: now.playId, paused: !now.paused })}
      >
        {pausing ? <Spinner size={28} /> : <Icon name={now.paused ? "play" : "pause"} size={34} />}
      </button>
      <div className="transport-side">
        <button
          className="round round-md round-ghost"
          data-testid="skip"
          aria-label="Skip song"
          disabled={skipping}
          onClick={() => void store.run("skip", { kind: "skip", playId: now.playId })}
        >
          {skipping ? <Spinner size={22} /> : <Icon name="skip" size={26} />}
        </button>
        <span className="round-label">Skip</span>
      </div>
    </div>
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
      <div className="card-scale">
        <span>Off</span>
        <span>Full</span>
      </div>
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
    <div className="card">
      <div className="card-head">
        <span className="card-title">
          <Icon name="note" size={18} /> Key
        </span>
        {now.semitones !== 0 && (
          <button className="link" data-testid="key-reset" disabled={busy} onClick={() => { setKey(0); }}>
            Reset
          </button>
        )}
      </div>
      <div className="stepper">
        <button
          className="round round-md round-ghost"
          data-testid="key-down"
          aria-label="Lower key"
          disabled={busy || now.semitones <= KEY_MIN}
          onClick={() => { stepKey(-1); }}
        >
          <Icon name="minus" />
        </button>
        <div className="stepper-value" data-testid="key-value">
          {busy ? <Spinner size={20} /> : formatKey(now.semitones)}
        </div>
        <button
          className="round round-md round-ghost"
          data-testid="key-up"
          aria-label="Raise key"
          disabled={busy || now.semitones >= KEY_MAX}
          onClick={() => { stepKey(1); }}
        >
          <Icon name="plus" />
        </button>
      </div>
      <div className="key-dots" aria-hidden="true">
        {Array.from({ length: KEY_MAX - KEY_MIN + 1 }, (_, i) => i + KEY_MIN).map((k) => (
          <span key={k} className={`key-dot ${k === now.semitones ? "is-on" : ""} ${k === 0 ? "is-zero" : ""}`} />
        ))}
      </div>
    </div>
  );
}

function UpNext(props: { view: PhoneView }): JSX.Element | null {
  const next = props.view.queue.slice(0, 3);
  if (next.length === 0) return null;
  return (
    <section className="section">
      <h3 className="section-title">Up next</h3>
      <ul className="list">
        {next.map((e) => (
          <li key={e.entryId} className="row">
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
    </section>
  );
}
