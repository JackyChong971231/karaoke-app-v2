// The TV is a reconciler, like the server shell: given the server's TvView, move the audio engine, video, and
// lyrics toward it. It never decides what plays next. It only reports what it observed (ended, failed, clock).

import type { LyricsDoc, TvCommand, TvView } from "../wire/generated";
import type { AudioEngine } from "./audio";
import type { LyricsRenderer } from "./lyrics";

export interface TvDeps {
  engine: AudioEngine;
  lyrics: LyricsRenderer;
  video: HTMLVideoElement;
  send(cmd: TvCommand): void;
  fetchLyrics(songId: string, signal: AbortSignal): Promise<LyricsDoc>;
}

/** Mutable, private to this module. Exactly one load in flight. */
interface Loaded { playId: number; abort: AbortController; ready: boolean }

export class TvReconciler {
  constructor(private readonly deps: TvDeps) {}

  /**
   * Apply a new snapshot. Safe to call with the same view twice.
   *
   * TODO pseudocode:
   *   if (view.play?.playId !== loaded?.playId) {
   *     loaded?.abort.abort(); engine.unload(); lyrics.setDoc(null); video.removeAttribute("src")
   *     if (view.play) {
   *       loaded = { playId, abort: new AbortController(), ready: false }
   *       try {
   *         [ , doc] = await Promise.all([engine.load(playId, songId, signal), fetchLyrics(songId, signal)])
   *         if (signal.aborted) return
   *         lyrics.setDoc(doc); video.src = `/media/${songId}/video.mp4`
   *         engine.start(view.play.resumeAtS); loaded.ready = true
   *       } catch (e) { if (!signal.aborted) send({ kind: "trackFailed", playId, reason: String(e) }) }
   *     }
   *   }
   *   if (loaded?.ready) {               // idempotent setters
   *     engine.setPaused(view.play.paused); engine.setKey(view.play.semitones)
   *   }
   *   engine.setVocal(view.vocalLevel); avOffset = view.avOffsetS
   */
  apply(view: TvView): void { void view; throw new Error("not implemented"); }

  /**
   * Every animation frame.
   * TODO pseudocode:
   *   a = engine.clock.position(); d = a + avOffset                    // display time
   *   lyrics.render(d)
   *   if playing and |video.currentTime - d| > 0.15: video.currentTime = d   // audio is the clock; video follows
   *   video paused state mirrors engine paused state
   *   if a >= engine.durationS() - 0.05 and !endedSent[playId]: send trackEnded(playId) once
   */
  frame(): void { throw new Error("not implemented"); }

  /** 4 Hz: socket.reportClock(playId, audible position, paused). Telemetry for phones and for resume-after-reload. */
  clockSample(): { playId: number; positionS: number; paused: boolean } | null { throw new Error("not implemented"); }
}
