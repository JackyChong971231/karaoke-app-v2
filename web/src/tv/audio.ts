// TV audio: the party's clock. The only file allowed to import signalsmith-stretch
// (eslint no-restricted-imports), so the library's traps are handled once, here.
//
// Graph per song:
//   stretch(4ch: inst L, inst R, voc L, voc R) -> splitter -> [0,1] -> merger -> destination
//                                                        -> [2,3] -> merger -> vocalGain -> destination
// The two stems live in ONE 4-channel buffer set, so they cannot drift apart.

import type { StretchChange, StretchNode } from "signalsmith-stretch";
import type SignalsmithStretch from "signalsmith-stretch";
import { mediaUrl } from "../wire/http";

declare const __STRETCH_URL__: string;
let stretchFactory: Promise<typeof SignalsmithStretch> | null = null;

/** The verbatim vendor copy from vite.config.ts, never bundled (see stretchVerbatim there). */
function loadStretch(): Promise<typeof SignalsmithStretch> {
  stretchFactory ??= import(/* @vite-ignore */ __STRETCH_URL__).then(
    (m: { default: typeof SignalsmithStretch }) => m.default,
  );
  return stretchFactory;
}

/**
 * The only way to construct the stretch node.
 * - numberOfInputs: 1 even though nothing connects: with 0 the node crashes the first time it processes while paused.
 * - setUpdateInterval(0.02): without it `inputTime` never updates.
 * - The output graph is connected before anything else is awaited: the worklet stops for good if it ever
 *   processes with no connected output.
 */
async function createStretchNode(ctx: AudioContext): Promise<{ node: StretchNode; vocalGain: GainNode }> {
  const create = await loadStretch();
  const node = await create(ctx, { numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [4] });
  const split = ctx.createChannelSplitter(4);
  const backing = ctx.createChannelMerger(2);
  const vocals = ctx.createChannelMerger(2);
  const vocalGain = ctx.createGain();
  node.connect(split);
  split.connect(backing, 0, 0);
  split.connect(backing, 1, 1);
  split.connect(vocals, 2, 0);
  split.connect(vocals, 3, 1);
  vocals.connect(vocalGain).connect(ctx.destination);
  backing.connect(ctx.destination);
  void node.setUpdateInterval(0.02);
  return { node, vocalGain };
}

interface Track {
  playId: number;
  songId: string;
  node: StretchNode;
  vocalGain: GainNode;
  durationS: number;
  latencyS: number;
}

/**
 * Audible position = inputTime - (stretch latency + baseLatency + outputLatency).
 *
 * The raw inputTime runs ahead of the speakers (prototype: 0.115 s stretch + 0.05 s output). It also updates by
 * message every 20 ms, so right after a seek it still reports the old position: the clock holds the target
 * until a fresh update lands near it.
 */
export class AudibleClock {
  private hold: { target: number; inputTimeAtSeek: number } | null = null;
  private frozen: number | null = null;
  private floor: number | null = null;
  private playing = false;

  constructor(
    private readonly ctx: AudioContext,
    private readonly track: () => Track | null,
  ) {}

  /** Seconds into the song that the room hears now. */
  position(): number {
    const track = this.track();
    if (track === null) return 0;
    const input = track.node.inputTime;
    if (this.hold !== null) {
      if (input !== this.hold.inputTimeAtSeek && Math.abs(input - this.hold.target) < 1) this.hold = null;
      else return this.hold.target;
    }
    if (!this.playing) return this.frozen ?? Math.max(0, input);
    // outputLatency is 0 or missing on some platforms until audio has flowed.
    const lead = track.latencyS + this.ctx.baseLatency + (this.ctx.outputLatency || 0);
    let p = Math.max(0, input - lead);
    // After a resume or a seek, inputTime restarts at the held position, so p would step back by `lead` and
    // filled words would un-fill. Never report less than that position until playback passes it.
    if (this.floor !== null) {
      if (p >= this.floor) this.floor = null;
      else p = this.floor;
    }
    return p;
  }

  noteSeek(target: number, inputTimeNow: number): void {
    this.hold = { target, inputTimeAtSeek: inputTimeNow };
    this.frozen = null;
    this.floor = target;
  }

  notePlaying(playing: boolean): void {
    if (playing === this.playing) return;
    const now = this.position();
    if (playing) {
      this.floor = now;
      this.frozen = null;
    } else {
      this.frozen = now;
    }
    this.playing = playing;
  }

  reset(): void {
    this.hold = null;
    this.frozen = null;
    this.floor = null;
    this.playing = false;
  }
}

export interface EngineProbe {
  loadedSongId: string | null;
  playId: number | null;
  paused: boolean;
  semitones: number;
  vocalGain: number;
  contextState: AudioContextState;
}

/** Plays one song at a time. Setters are idempotent, so the reconciler may call them on every view. */
export class AudioEngine {
  readonly clock: AudibleClock;
  private track: Track | null = null;
  private paused = true;
  private semitones = 0;
  private vocalLevel = 1;
  private inputEndSeenAt: number | null = null;

  private constructor(private readonly ctx: AudioContext) {
    this.clock = new AudibleClock(ctx, () => this.track);
  }

  /** A kiosk launch has the Edge autoplay flag. A page opened by hand starts suspended until one click. */
  static create(): AudioEngine {
    return new AudioEngine(new AudioContext());
  }

  needsGesture(): boolean {
    return this.ctx.state === "suspended";
  }

  async unlock(): Promise<void> {
    await this.ctx.resume();
  }

  onStateChange(listener: () => void): void {
    this.ctx.addEventListener("statechange", listener);
  }

  /** Fetch and decode both stems, build the 4-channel buffers on a fresh node. Resolves when playable. */
  async load(playId: number, songId: string, signal: AbortSignal): Promise<{ durationS: number }> {
    this.unload();
    const decode = async (file: "instrumental.opus" | "vocals.opus"): Promise<AudioBuffer> => {
      const res = await fetch(mediaUrl(songId, file), { signal });
      if (!res.ok) throw new Error(`${file}: HTTP ${String(res.status)}`);
      return this.ctx.decodeAudioData(await res.arrayBuffer());
    };
    const [inst, voc] = await Promise.all([decode("instrumental.opus"), decode("vocals.opus")]);
    signal.throwIfAborted();
    const { node, vocalGain } = await createStretchNode(this.ctx);
    vocalGain.gain.value = this.vocalLevel;
    if (signal.aborted) {
      node.disconnect();
      signal.throwIfAborted();
    }
    const ch = (b: AudioBuffer, i: number): Float32Array => b.getChannelData(Math.min(i, b.numberOfChannels - 1));
    await node.addBuffers([ch(inst, 0), ch(inst, 1), ch(voc, 0), ch(voc, 1)]);
    const latencyS = await node.latency();
    if (signal.aborted) {
      node.disconnect();
      signal.throwIfAborted();
    }
    const durationS = Math.min(inst.duration, voc.duration);
    this.track = { playId, songId, node, vocalGain, durationS, latencyS };
    this.paused = true;
    this.clock.reset();
    this.at({ active: false, input: 0, semitones: this.semitones });
    return { durationS };
  }

  /** Start from `fromS`, playing or paused. A reload resumes at the last reported position. */
  start(fromS: number, paused: boolean, semitones: number): void {
    const track = this.track;
    if (track === null) return;
    this.paused = paused;
    this.semitones = semitones;
    this.inputEndSeenAt = null;
    this.clock.noteSeek(fromS, track.node.inputTime);
    this.at({ input: fromS, active: !paused, semitones });
    this.clock.notePlaying(!paused);
  }

  /** Jump within the loaded song, playing or paused. The clock holds the target until the node reports it. */
  seek(toS: number): void {
    const track = this.track;
    if (track === null) return;
    const target = Math.max(0, Math.min(toS, track.durationS));
    this.inputEndSeenAt = null;
    this.clock.noteSeek(target, track.node.inputTime);
    this.at({ input: target });
  }

  setPaused(paused: boolean): void {
    if (this.track === null || paused === this.paused) return;
    this.paused = paused;
    this.clock.notePlaying(!paused);
    this.at({ active: !paused });
  }

  /** Takes effect at once: no reprocessing, the node shifts pitch in real time. */
  setKey(semitones: number): void {
    if (this.track === null || semitones === this.semitones) return;
    this.semitones = semitones;
    this.at({ semitones });
  }

  /** Vocal channels' gain, applied after the key change. 0 is off, 1 is full. */
  setVocal(level: number): void {
    if (level === this.vocalLevel) return;
    this.vocalLevel = level;
    this.track?.vocalGain.gain.setTargetAtTime(level, this.ctx.currentTime, 0.03);
  }

  unload(): void {
    const track = this.track;
    if (track === null) return;
    this.track = null;
    this.clock.reset();
    track.node.schedule({ active: false });
    track.node.disconnect();
    void track.node.dropBuffers();
  }

  durationS(): number {
    return this.track?.durationS ?? 0;
  }

  playId(): number | null {
    return this.track?.playId ?? null;
  }

  isPaused(): boolean {
    return this.paused;
  }

  /** True once the room has heard the end of the song. */
  finished(): boolean {
    const track = this.track;
    if (track === null || this.paused) return false;
    if (this.clock.position() >= track.durationS - 0.05) return true;
    // inputTime may stop at the buffer end, so the audible position never reaches it. Wait out the lead instead.
    if (track.node.inputTime >= track.durationS - 0.02) {
      this.inputEndSeenAt ??= performance.now();
      return performance.now() - this.inputEndSeenAt > (track.latencyS + 0.3) * 1000;
    }
    return false;
  }

  probe(): EngineProbe {
    return {
      loadedSongId: this.track?.songId ?? null,
      playId: this.track?.playId ?? null,
      paused: this.paused,
      semitones: this.semitones,
      vocalGain: this.vocalLevel,
      contextState: this.ctx.state,
    };
  }

  private at(change: StretchChange): void {
    const track = this.track;
    if (track === null) return;
    track.node.schedule({ output: this.ctx.currentTime + track.latencyS, ...change });
  }
}
