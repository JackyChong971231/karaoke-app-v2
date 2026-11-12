// Everything on the TV that is not video or lyrics. Re-renders only on a new snapshot or stage change.

import type { JSX } from "react";
import QRCode from "qrcode";
import { useEffect, useState, useSyncExternalStore } from "react";
import type { PartySocket } from "../wire/socket";
import type { RestartOfferView, TvCommand, TvPlay, TvView, UpNext } from "../wire/types";
import type { AudioEngine } from "./audio";
import type { Stage } from "./reconcile";

interface StageSource {
  get: () => Stage;
  subscribe: (listener: () => void) => () => void;
}

export function Overlays(props: {
  socket: PartySocket<TvView, TvCommand>;
  engine: AudioEngine;
  stage: StageSource;
}): JSX.Element {
  const { socket, engine } = props;
  const view = useSyncExternalStore(socket.subscribe, socket.view);
  const link = useSyncExternalStore(socket.subscribe, socket.link);
  const stage = useSyncExternalStore(props.stage.subscribe, props.stage.get);
  const needsGesture = useNeedsGesture(engine);

  if (link === "superseded") {
    return (
      <div className="tv-fullscreen tv-center">
        <div className="tv-message">
          <h1>Opened in another window</h1>
          <p>This screen stopped so the other one can play. Close this window.</p>
        </div>
      </div>
    );
  }

  const play = view?.play ?? null;
  return (
    <>
      {play === null || stage.kind === "idle" ? (
        <IdleScreen view={view} />
      ) : (
        <PlayingChrome play={play} stage={stage} />
      )}
      {view !== null && <SideRail view={view} showQr={play !== null} />}
      {view?.restartOffer != null && <RestartPrompt offer={view.restartOffer} socket={socket} />}
      {link === "connecting" && <div className="tv-pill tv-reconnect">Reconnecting to the laptop…</div>}
      {needsGesture && (
        <button
          className="tv-fullscreen tv-center tv-start"
          data-testid="tv-start"
          onClick={() => void engine.unlock()}
        >
          <span className="tv-start-button">
            <PlayGlyph /> Start karaoke
          </span>
          <span className="tv-start-hint">The browser needs one click before it can play sound.</span>
        </button>
      )}
    </>
  );
}

function useNeedsGesture(engine: AudioEngine): boolean {
  const [needs, setNeeds] = useState(() => engine.needsGesture());
  useEffect(() => {
    engine.onStateChange(() => { setNeeds(engine.needsGesture()); });
    // Edge resumes a context created before the autoplay flag applied, a moment after load.
    const t = window.setTimeout(() => { setNeeds(engine.needsGesture()); }, 600);
    return () => { window.clearTimeout(t); };
  }, [engine]);
  return needs;
}

function PlayingChrome(props: { play: TvPlay; stage: Stage }): JSX.Element {
  const { play, stage } = props;
  const [intro, setIntro] = useState(true);
  useEffect(() => {
    setIntro(true);
    const t = window.setTimeout(() => { setIntro(false); }, 7000);
    return () => { window.clearTimeout(t); };
  }, [play.playId]);

  return (
    <>
      <div className="tv-scrim-top" />
      <div className="tv-scrim-bottom" />
      <div className={`tv-now ${intro ? "is-intro" : ""}`} data-testid="tv-now">
        <div className="tv-now-label">{play.singerName === null ? "Sing along" : "Now singing"}</div>
        <div className="tv-now-title">{play.song.title}</div>
        <div className="tv-now-meta">
          <span>{play.song.artist}</span>
          {play.singerName !== null && (
            <>
              <span className="tv-dot" />
              <span className="tv-now-singer">
                <MicGlyph /> {play.singerName}
              </span>
            </>
          )}
        </div>
        {(play.lyricsFlagged || play.semitones !== 0) && (
          <div className="tv-badges">
            {play.lyricsFlagged && (
              <span className="tv-badge tv-badge-warn" data-testid="tv-lyrics-flagged">
                Lyrics may be wrong
              </span>
            )}
            {play.semitones !== 0 && (
              <span className="tv-badge">Key {play.semitones > 0 ? `+${String(play.semitones)}` : play.semitones}</span>
            )}
          </div>
        )}
      </div>
      {play.paused && stage.kind === "playing" && (
        <div className="tv-paused" data-testid="tv-paused">
          <PauseGlyph /> Paused
        </div>
      )}
      {stage.kind === "loading" && (
        <div className="tv-fullscreen tv-center tv-loading">
          <div className="tv-loading-card">
            <div className="tv-spinner" />
            <div className="tv-loading-label">{play.singerName === null ? "Sing along" : `Up now: ${play.singerName}`}</div>
            <div className="tv-loading-title">{play.song.title}</div>
            <div className="tv-loading-artist">{play.song.artist}</div>
          </div>
        </div>
      )}
      {stage.kind === "failed" && <div className="tv-pill tv-failed">This song could not play. Moving on…</div>}
    </>
  );
}

function SideRail(props: { view: TvView; showQr: boolean }): JSX.Element {
  const { view, showQr } = props;
  return (
    <div className="tv-rail">
      {showQr && (
        <div className="tv-qr-card" data-testid="tv-qr">
          <Qr url={view.joinUrl} size="15vh" />
          <div className="tv-qr-caption">Scan to sing</div>
        </div>
      )}
      {view.upNext !== null && showQr && <UpNextCard next={view.upNext} />}
    </div>
  );
}

function UpNextCard(props: { next: UpNext }): JSX.Element {
  const { next } = props;
  return (
    <div className="tv-next" data-testid="tv-up-next">
      <div className="tv-next-label">Up next</div>
      <div className="tv-next-title">{next.title}</div>
      <div className="tv-next-singer">
        <MicGlyph /> {next.singerName}
      </div>
      {!next.ready && (
        <div className="tv-next-preparing">
          <span className="tv-mini-spinner" /> Preparing
        </div>
      )}
    </div>
  );
}

function IdleScreen(props: { view: TvView | null }): JSX.Element {
  const view = props.view;
  return (
    <div className="tv-fullscreen tv-idle" data-testid="tv-idle">
      <div className="tv-idle-glow" />
      <div className="tv-idle-content">
        <div className="tv-idle-text">
          <div className="tv-brand">
            <MicGlyph /> Karaoke
          </div>
          <h1>Scan to pick a song</h1>
          <p>Point your phone camera at the code. Queue a song and it plays here.</p>
          {view?.upNext != null && (
            <div className="tv-idle-next" data-testid="tv-preparing">
              <div className="tv-progress">
                <div className={`tv-progress-bar ${view.upNext.ready ? "is-done" : ""}`} />
              </div>
              <div>
                {view.upNext.ready ? "Starting " : "Preparing "}
                <strong>{view.upNext.title}</strong> for {view.upNext.singerName}
              </div>
            </div>
          )}
          {view !== null && <div className="tv-idle-url">{view.joinUrl}</div>}
        </div>
        {view !== null && (
          <div className="tv-idle-qr" data-testid="tv-qr">
            <Qr url={view.joinUrl} size="42vh" />
          </div>
        )}
      </div>
    </div>
  );
}

function RestartPrompt(props: { offer: RestartOfferView; socket: PartySocket<TvView, TvCommand> }): JSX.Element {
  const { offer, socket } = props;
  const [pending, setPending] = useState<boolean | null>(null);
  const answer = (keep: boolean): void => {
    setPending(keep);
    socket
      .send({ kind: "resolveRestart", keep })
      .catch(() => undefined)
      .finally(() => { setPending(null); });
  };
  const shown = offer.entries.slice(0, 6);
  return (
    <div className="tv-fullscreen tv-center tv-modal-backdrop" data-testid="tv-restart">
      <div className="tv-modal">
        <div className="tv-modal-label">Welcome back</div>
        <h2>Keep the last queue?</h2>
        <p>
          {offer.entries.length} {offer.entries.length === 1 ? "song was" : "songs were"} waiting when the app closed
          {offer.singerNames.length > 0 && <>, from {offer.singerNames.join(", ")}</>}.
        </p>
        <ol className="tv-modal-list">
          {shown.map((s, i) => (
            <li key={`${s.songId}-${String(i)}`}>
              <span className="tv-modal-title">{s.title}</span>
              <span className="tv-modal-artist">{s.artist}</span>
            </li>
          ))}
          {offer.entries.length > shown.length && (
            <li className="tv-modal-more">and {offer.entries.length - shown.length} more</li>
          )}
        </ol>
        <div className="tv-modal-actions">
          <button className="tv-btn" disabled={pending !== null} onClick={() => { answer(false); }}>
            {pending === false ? <span className="tv-mini-spinner" /> : null} Start new
          </button>
          <button className="tv-btn tv-btn-primary" disabled={pending !== null} onClick={() => { answer(true); }}>
            {pending === true ? <span className="tv-mini-spinner" /> : null} Keep queue
          </button>
        </div>
        <div className="tv-modal-hint">Anyone can answer from their phone too.</div>
      </div>
    </div>
  );
}

function Qr(props: { url: string; size: string }): JSX.Element {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    QRCode.toString(props.url, { type: "svg", margin: 0, errorCorrectionLevel: "M" })
      .then((svg) => {
        if (live) setSrc(`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [props.url]);
  return (
    <div className="tv-qr" style={{ width: props.size, height: props.size }}>
      {src !== null && <img src={src} alt={`QR code for ${props.url}`} />}
    </div>
  );
}

function MicGlyph(): JSX.Element {
  return (
    <svg className="tv-glyph" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M12 14a3 3 0 0 0 3-3V5a3 3 0 1 0-6 0v6a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11h-2Z"
      />
    </svg>
  );
}

function PlayGlyph(): JSX.Element {
  return (
    <svg className="tv-glyph" viewBox="0 0 24 24" aria-hidden="true">
      <path fill="currentColor" d="M8 5.14v13.72a1 1 0 0 0 1.52.85l10.9-6.86a1 1 0 0 0 0-1.7L9.52 4.29A1 1 0 0 0 8 5.14Z" />
    </svg>
  );
}

function PauseGlyph(): JSX.Element {
  return (
    <svg className="tv-glyph" viewBox="0 0 24 24" aria-hidden="true">
      <path fill="currentColor" d="M7 5h3.5v14H7zM13.5 5H17v14h-3.5z" />
    </svg>
  );
}
