// TV page entry (tv.html). Wiring only: socket -> reconciler, rAF -> reconciler.frame, overlays in React.

import { createRoot } from "react-dom/client";
import { api } from "../wire/http";
import { connectTv } from "../wire/socket";
import { AudioEngine } from "./audio";
import { LyricsRenderer } from "./lyrics";
import { Overlays } from "./Overlays";
import { TvReconciler, type Stage } from "./reconcile";
import "./tv.css";

declare global {
  interface Window {
    /** Read-only probe for the verification harness. Present in every build; costs nothing until called. */
    __karaokeTv?: { probe(): unknown };
  }
}

function byId<T extends HTMLElement>(id: string, type: new () => T): T {
  const el = document.getElementById(id);
  if (!(el instanceof type)) throw new Error(`tv.html is missing #${id}`);
  return el;
}

function boot(): void {
  const video = byId("video", HTMLVideoElement);
  const engine = AudioEngine.create();
  const lyrics = new LyricsRenderer(
    [byId("slot0", HTMLDivElement), byId("slot1", HTMLDivElement)],
    byId("lyricsBreak", HTMLDivElement),
  );
  const socket = connectTv();

  let stage: Stage = { kind: "idle" };
  const stageListeners = new Set<() => void>();
  const rec = new TvReconciler({
    engine,
    lyrics,
    video,
    send: (cmd) => void socket.send(cmd).catch(() => undefined),
    fetchLyrics: api.lyrics,
    fetchAdvancedLyrics: api.advancedLyrics,
    onStage: (next) => {
      stage = next;
      for (const l of stageListeners) l();
    },
  });

  socket.subscribe(() => {
    const view = socket.view();
    if (view !== null) rec.apply(view);
  });

  const tick = (): void => {
    rec.frame();
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);

  window.setInterval(() => {
    const s = rec.clockSample();
    if (s !== null) socket.reportClock(s.playId, s.positionS, s.paused);
  }, 250);

  window.__karaokeTv = {
    probe: () => ({
      ...engine.probe(),
      audible: engine.clock.position(),
      display: rec.displayTime(),
      videoTime: video.currentTime,
      stage,
      ...lyrics.probe(),
    }),
  };

  const rootEl = byId("overlay", HTMLDivElement);
  createRoot(rootEl).render(
    <Overlays
      socket={socket}
      engine={engine}
      stage={{
        get: () => stage,
        subscribe: (l) => {
          stageListeners.add(l);
          return () => stageListeners.delete(l);
        },
      }}
    />,
  );
}

boot();
