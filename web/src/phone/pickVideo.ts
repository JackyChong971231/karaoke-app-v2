// The pick-a-video flow. Per-phone UI state, so it lives here and not in the party reducer: nobody else needs to
// see that this phone is choosing a video.
//
//   idle --choose(song)--> resolving --official(pickId)----------------> queuing --accepted--> idle
//                                    \--choose(candidates)--> choosing --tap(pickId)--^      \--rejected--> failed
//                                    \--error----------------------------------------------------------> failed
//   any --cancel--> idle      (a late response for a cancelled song is ignored: events carry the song key)

import { api } from "../wire/http";
import { assertNever } from "../wire/socket";
import type { OnlineSongHit, Outcome, VideoCandidateView, VideoChoiceResponse } from "../wire/types";
import { rejectText } from "./text";

export type PickFlow =
  | { step: "idle" }
  | { step: "resolving"; song: OnlineSongHit }
  | { step: "choosing"; song: OnlineSongHit; candidates: VideoCandidateView[] }
  /** `candidates` is null when the official video was found, so no sheet was shown. */
  | { step: "queuing"; song: OnlineSongHit; pickId: string; candidates: VideoCandidateView[] | null }
  | { step: "failed"; song: OnlineSongHit; message: string };

export type PickEvent =
  | { type: "choose"; song: OnlineSongHit }
  | { type: "resolved"; songKey: string; response: VideoChoiceResponse }
  | { type: "resolveFailed"; songKey: string }
  | { type: "tap"; pickId: string }
  | { type: "replied"; pickId: string; outcome: Outcome | null }
  | { type: "cancel" };

/** What the flow wants done next. The controller performs it and feeds the result back as an event. */
export type PickTask = { task: "fetchVideoChoice"; songKey: string } | { task: "queuePick"; pickId: string } | null;

export function pickReducer(flow: PickFlow, ev: PickEvent): [PickFlow, PickTask] {
  switch (ev.type) {
    case "choose":
      return [{ step: "resolving", song: ev.song }, { task: "fetchVideoChoice", songKey: ev.song.onlineKey }];
    case "resolved": {
      if (flow.step !== "resolving" || flow.song.onlineKey !== ev.songKey) return [flow, null];
      const r = ev.response;
      switch (r.kind) {
        case "official":
          return [
            { step: "queuing", song: flow.song, pickId: r.pickId, candidates: null },
            { task: "queuePick", pickId: r.pickId },
          ];
        case "choose":
          if (r.candidates.length === 0) {
            return [{ step: "failed", song: flow.song, message: "No videos found for this song" }, null];
          }
          return [{ step: "choosing", song: flow.song, candidates: r.candidates }, null];
        default:
          return assertNever(r);
      }
    }
    case "resolveFailed":
      if (flow.step !== "resolving" || flow.song.onlineKey !== ev.songKey) return [flow, null];
      return [{ step: "failed", song: flow.song, message: "Couldn't look up videos. Try again." }, null];
    case "tap": {
      if (flow.step !== "choosing" || !flow.candidates.some((c) => c.pickId === ev.pickId)) return [flow, null];
      return [
        { step: "queuing", song: flow.song, pickId: ev.pickId, candidates: flow.candidates },
        { task: "queuePick", pickId: ev.pickId },
      ];
    }
    case "replied": {
      if (flow.step !== "queuing" || flow.pickId !== ev.pickId) return [flow, null];
      const outcome = ev.outcome;
      if (outcome === null) return [{ step: "failed", song: flow.song, message: "Not connected. Try again." }, null];
      switch (outcome.kind) {
        case "accepted":
          return [{ step: "idle" }, null];
        case "rejected":
          return [{ step: "failed", song: flow.song, message: rejectText[outcome.reason] }, null];
        default:
          return assertNever(outcome);
      }
    }
    case "cancel":
      return [{ step: "idle" }, null];
    default:
      return assertNever(ev);
  }
}

/** Runs the flow's tasks. `commit` turns a pick into a queued song (phone) or a corrected match (import page). */
export class PickController {
  private flow: PickFlow = { step: "idle" };
  private readonly listeners = new Set<() => void>();

  /** `fetch` defaults to the import page's lookup, which queues an official video with no question.
   *  Phones pass `api.videoOptions`, which always returns a list to choose from. */
  constructor(
    private readonly commit: (pickId: string) => Promise<Outcome | null>,
    private readonly onDone: (song: OnlineSongHit) => void,
    private readonly fetch: (key: string, signal: AbortSignal) => Promise<VideoChoiceResponse> = api.videoChoice,
  ) {}

  get = (): PickFlow => this.flow;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  dispatch = (ev: PickEvent): void => {
    const before = this.flow;
    const [next, task] = pickReducer(this.flow, ev);
    this.flow = next;
    if (next !== before) for (const l of this.listeners) l();
    if (before.step === "queuing" && next.step === "idle") this.onDone(before.song);
    if (task === null) return;
    switch (task.task) {
      case "fetchVideoChoice": {
        const songKey = task.songKey;
        this.fetch(songKey, new AbortController().signal).then(
          (response) => { this.dispatch({ type: "resolved", songKey, response }); },
          () => { this.dispatch({ type: "resolveFailed", songKey }); },
        );
        return;
      }
      case "queuePick": {
        const pickId = task.pickId;
        this.commit(pickId).then(
          (outcome) => { this.dispatch({ type: "replied", pickId, outcome }); },
          () => { this.dispatch({ type: "replied", pickId, outcome: null }); },
        );
        return;
      }
      default:
        assertNever(task);
    }
  };
}
