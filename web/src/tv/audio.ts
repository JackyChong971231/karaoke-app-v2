// TV audio: the party's clock. The only file allowed to import signalsmith-stretch
// (eslint no-restricted-imports), so the two library traps are handled once, here, for good.
//
// Graph per song:
//   stretch(4ch: inst L, inst R, voc L, voc R) -> splitter -> [0,1] -> merger -> destination
//                                                        -> [2,3] -> merger -> vocalGain -> destination
// The two stems live in ONE 4-channel buffer set, so they cannot drift apart.

export interface StretchNode extends AudioNode {
  inputTime: number;
  schedule(change: { output?: number; input?: number; active?: boolean; semitones?: number }): void;
  addBuffers(channels: Float32Array[]): Promise<void>;
  latency(): Promise<number>;
  setUpdateInterval(seconds: number): void;
}

/**
 * The ONLY way to construct the stretch node.
 * - numberOfInputs: 1 even though nothing connects: with 0 the node crashes the first time it processes while paused.
 * - setUpdateInterval(0.02): without it `inputTime` never updates.
 * - The output graph is connected BEFORE anything is awaited: the worklet stops for good if it ever processes
 *   with no connected output. Returns the node plus the vocal gain it wired.
 */
export async function createStretchNode(ctx: AudioContext): Promise<{ node: StretchNode; vocalGain: GainNode }> {
  void ctx;
  throw new Error("not implemented");
}

/**
 * Audible position = inputTime - (stretch latency + baseLatency + outputLatency), held across seeks.
 *
 * The raw inputTime runs ahead of the speakers (prototype: 0.115 s stretch + 0.05 s output). It also updates by
 * message every 20 ms, so right after a seek it still reports the OLD position.
 */
export class AudibleClock {
  constructor(private readonly node: () => StretchNode | null, private readonly ctx: AudioContext) {}

  /** Seconds into the song that the room hears now. */
  position(): number {
    // TODO pseudocode:
    //   if (hold) {
    //     // release only on a fresh update that has landed near the target
    //     if (node.inputTime !== hold.inputTimeAtSeek && Math.abs(node.inputTime - hold.target) < 1) hold = null
    //     else return hold.target
    //   }
    //   lead = playing ? stretchLatency + ctx.baseLatency + (ctx.outputLatency || 0) : 0
    //   p = max(0, node.inputTime - lead)
    //   // On resume, inputTime starts at the paused position, so p would jump BACK by `lead` and words would
    //   // un-fill. Clamp: never report less than the position at the moment play was pressed, until p passes it.
    //   if (resumeFloor !== null) { if (p >= resumeFloor) resumeFloor = null; else p = resumeFloor }
    //   return p
    throw new Error("not implemented");
  }

  /** Call right after scheduling a seek: hold `target` until the node reports a new time. */
  noteSeek(target: number): void { void target; throw new Error("not implemented"); }
  notePlaying(playing: boolean): void { void playing; throw new Error("not implemented"); }
  setStretchLatency(seconds: number): void { void seconds; throw new Error("not implemented"); }
}

export interface EngineProbe { loadedSongId: string | null; playId: number | null; paused: boolean; semitones: number; vocalGain: number }

/** Plays one song at a time. Idempotent setters; the reconciler may call them every view. */
export class AudioEngine {
  readonly clock: AudibleClock;

  private constructor(ctx: AudioContext) {
    this.clock = new AudibleClock(() => null, ctx);
    throw new Error("not implemented");
  }

  /** Needs the Edge autoplay flag on the kiosk launch (no user gesture on a TV). */
  static async create(): Promise<AudioEngine> { throw new Error("not implemented"); }

  /**
   * Fetch /media/<id>/instrumental.opus and vocals.opus, decode, build the 4-channel buffers, create a fresh node.
   * `signal` aborts a load that a newer view made obsolete (skip during loading). Resolves when playable.
   * Throws a LoadError the reconciler turns into a `trackFailed` command.
   */
  async load(playId: number, songId: string, signal: AbortSignal): Promise<{ durationS: number }> {
    void playId; void songId; void signal;
    throw new Error("not implemented");
  }

  /** Start or continue from `fromS` (resume after reload passes resumeAtS). */
  start(fromS: number): void { void fromS; throw new Error("not implemented"); }
  setPaused(paused: boolean): void { void paused; throw new Error("not implemented"); }
  /** Takes effect at once: schedule({ output: ctx.currentTime + latency, semitones }). */
  setKey(semitones: number): void { void semitones; throw new Error("not implemented"); }
  /** Vocal channels' gain, applied after the key change. 0 = off, 1 = full. */
  setVocal(level: number): void { void level; throw new Error("not implemented"); }
  unload(): void { throw new Error("not implemented"); }
  durationS(): number { throw new Error("not implemented"); }
  probe(): EngineProbe { throw new Error("not implemented"); }
}
