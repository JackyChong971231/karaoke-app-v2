declare module "signalsmith-stretch" {
  export interface StretchChange {
    output?: number;
    input?: number;
    active?: boolean;
    semitones?: number;
  }

  export interface StretchNode extends AudioWorkletNode {
    inputTime: number;
    schedule(change: StretchChange): void;
    addBuffers(channels: Float32Array[]): Promise<number>;
    dropBuffers(): Promise<unknown>;
    latency(): Promise<number>;
    setUpdateInterval(seconds: number): Promise<unknown>;
  }

  export default function SignalsmithStretch(
    context: BaseAudioContext,
    options?: AudioWorkletNodeOptions,
  ): Promise<StretchNode>;
}
