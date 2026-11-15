// The TV is a reconciler, like the server shell: given the server's TvView, move the audio engine, video, and
// lyrics toward it. It never decides what plays next. It only reports what it observed (ended, failed, clock).

import { mediaUrl } from "../wire/http";
import type { LyricsDoc, TvCommand, TvPlay, TvView } from "../wire/types";
import type { AudioEngine } from "./audio";
import type { LyricsRenderer } from "./lyrics";

export interface TvDeps {
  engine: AudioEngine;
  lyrics: LyricsRenderer;
  video: HTMLVideoElement;
  send(cmd: TvCommand): void;
  fetchLyrics(songId: string, signal: AbortSignal): Promise<LyricsDoc>;
  /** lyrics.advanced.json, or null when the song has none (matching failed, or no LRCLIB lyrics). */
  fetchAdvancedLyrics(songId: string, signal: AbortSignal): Promise<LyricsDoc | null>;
  onStage(stage: Stage): void;
}

/** What the TV is doing with the current play, for the overlay. */
export type Stage =
  | { kind: "idle" }
  | { kind: "loading"; playId: number }
  | { kind: "playing"; playId: number }
  | { kind: "failed"; playId: number };

/** Exactly one load in flight. */
interface Loaded {
  playId: number;
  abort: AbortController;
  ready: boolean;
  endedSent: boolean;
  lyrics: { current: LyricsDoc; advanced: LyricsDoc | null } | null;
}

const VIDEO_DRIFT_S = 0.15;
const FAILED_HOLD_MS = 3000;

export class TvReconciler {
  private loaded: Loaded | null = null;
  private latest: TvView | null = null;
  private avOffsetS = 0;

  constructor(private readonly deps: TvDeps) {}

  /** Apply a new snapshot. Safe to call with the same view twice. */
  apply(view: TvView): void {
    this.latest = view;
    const { engine } = this.deps;
    const play = view.play;
    if (play?.playId !== this.loaded?.playId) this.switchTo(play);
    if (play !== null && this.loaded?.ready === true) {
      engine.setPaused(play.paused);
      engine.setKey(play.semitones);
    }
    engine.setVocal(view.vocalLevel);
    this.avOffsetS = view.avOffsetS;
    this.pickLyrics();
  }

  /** The advanced lyrics switch takes effect on the next frame, mid-song too: both docs are already loaded. */
  private pickLyrics(): void {
    const docs = this.loaded?.lyrics;
    if (docs === null || docs === undefined) return;
    const advanced = this.latest?.advancedLyrics === true ? docs.advanced : null;
    this.deps.lyrics.setDoc(advanced ?? docs.current);
  }

  /** Every animation frame. */
  frame(): void {
    const loaded = this.loaded;
    const { engine, lyrics, video } = this.deps;
    if (loaded?.ready !== true) return;
    const display = engine.clock.position() + this.avOffsetS;
    lyrics.render(display);
    if (engine.isPaused()) {
      if (!video.paused) video.pause();
    } else {
      if (video.readyState >= HTMLMediaElement.HAVE_METADATA) {
        const target = Math.min(display, Number.isFinite(video.duration) ? video.duration : display);
        if (Math.abs(video.currentTime - target) > VIDEO_DRIFT_S) video.currentTime = target;
      }
      if (video.paused && !video.ended) void video.play().catch(() => undefined);
    }
    if (!loaded.endedSent && engine.finished()) {
      loaded.endedSent = true;
      this.deps.send({ kind: "trackEnded", playId: loaded.playId });
    }
  }

  /** Telemetry for phones and for resume after a TV reload. */
  clockSample(): { playId: number; positionS: number; paused: boolean } | null {
    const loaded = this.loaded;
    if (loaded?.ready !== true) return null;
    const { engine } = this.deps;
    return { playId: loaded.playId, positionS: engine.clock.position(), paused: engine.isPaused() };
  }

  displayTime(): number {
    return this.deps.engine.clock.position() + this.avOffsetS;
  }

  private switchTo(play: TvPlay | null): void {
    const { engine, lyrics, video } = this.deps;
    this.loaded?.abort.abort();
    engine.unload();
    lyrics.setDoc(null);
    video.pause();
    video.removeAttribute("src");
    video.load();
    if (play === null) {
      this.loaded = null;
      this.deps.onStage({ kind: "idle" });
      return;
    }
    const loaded: Loaded = {
      playId: play.playId,
      abort: new AbortController(),
      ready: false,
      endedSent: false,
      lyrics: null,
    };
    this.loaded = loaded;
    this.deps.onStage({ kind: "loading", playId: play.playId });
    void this.load(loaded, play);
  }

  private async load(loaded: Loaded, play: TvPlay): Promise<void> {
    const { engine, video } = this.deps;
    const { signal } = loaded.abort;
    try {
      const [, current, advanced] = await Promise.all([
        engine.load(play.playId, play.song.songId, signal),
        this.deps.fetchLyrics(play.song.songId, signal),
        // Never fails the song: without advanced lyrics, the switch has no effect on it.
        this.deps.fetchAdvancedLyrics(play.song.songId, signal).catch(() => null),
      ]);
      signal.throwIfAborted();
      loaded.lyrics = { current, advanced };
      this.pickLyrics();
      video.src = mediaUrl(play.song.songId, "video.mp4");
      // The view may have moved on (pause, key) while loading, so start from the latest snapshot, not `play`.
      const now = this.latest?.play?.playId === play.playId ? this.latest.play : play;
      engine.start(play.resumeAtS, now.paused, now.semitones);
      video.currentTime = play.resumeAtS + this.avOffsetS;
      loaded.ready = true;
      this.deps.onStage({ kind: "playing", playId: play.playId });
    } catch (e) {
      if (signal.aborted) return;
      this.deps.onStage({ kind: "failed", playId: play.playId });
      // Hold the message on screen before moving on. Without the pause, a song that fails every time turns into
      // a tight fail-and-retry loop.
      await new Promise((resolve) => setTimeout(resolve, FAILED_HOLD_MS));
      if (this.loaded !== loaded) return;
      this.deps.send({ kind: "trackFailed", playId: play.playId, reason: e instanceof Error ? e.message : String(e) });
    }
  }
}
