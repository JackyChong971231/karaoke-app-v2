// TV page entry (tv.html). Wiring only: socket -> reconciler, rAF -> reconciler.frame, overlays in React.
//
// Overlays (React, re-render only on a new snapshot):
//   - QR code for view.joinUrl, always visible (corner).
//   - "Next: <title> - <singer>" from view.upNext (dimmed with a spinner icon when not ready).
//   - Now: title, artist, singer (or "Sing along" for a filler).
//   - "Lyrics may be wrong" badge when play.lyricsFlagged.
//   - Idle screen (no play): big QR + "Scan to sing".
//   - Restart prompt when view.restartOffer: list + Keep / Start new buttons (clickable with the laptop mouse);
//     sends tvCommand resolveRestart. Same prompt shows on every phone; the first answer wins on the server.
//   - "Opened in another window" on superseded.

import { connectParty } from "../wire/socket";
import { AudioEngine } from "./audio";
import { LyricsRenderer } from "./lyrics";
import { TvReconciler } from "./reconcile";

declare global {
  interface Window {
    /** Read-only probe for the verification harness. Present in every build; costs nothing until called. */
    __karaokeTv?: { probe(): unknown };
  }
}

export async function boot(): Promise<void> {
  // TODO pseudocode:
  //   engine = await AudioEngine.create(); lyrics = new LyricsRenderer([slot0, slot1])
  //   socket = connectParty({ role: "tv" })
  //   rec = new TvReconciler({ engine, lyrics, video, send: c => socket.send(c), fetchLyrics })
  //   socket.subscribe(() => { const v = socket.view(); if (v) rec.apply(v) })
  //   requestAnimationFrame loop -> rec.frame()
  //   setInterval(250) -> s = rec.clockSample(); s && socket.reportClock(s.playId, s.positionS, s.paused)
  //   window.__karaokeTv = { probe: () => ({ ...engine.probe(), audible: engine.clock.position(), ...lyrics.probe(),
  //                                          videoTime: video.currentTime }) }
  //   render <Overlays socket={socket} /> into #overlay
  void connectParty; void AudioEngine; void LyricsRenderer; void TvReconciler;
  throw new Error("not implemented");
}
