// The pick-a-video flow. Per-phone UI state, so it lives here and not in the party reducer: nobody else needs to
// see that this phone is choosing a video. Pure reducer, unit-tested without a browser.
//
//   idle --choose(song)--> resolving --official(pickId)----------------> queuing --accepted--> idle (toast "Queued")
//                                    \--choose(candidates)--> choosing --tap(pickId)--^      \--rejected--> failed
//                                    \--error----------------------------------------------------------> failed
//   any --cancel--> idle      (a late response for a cancelled song is ignored: events carry the song key)

import type { OnlineSongHit, Outcome, VideoCandidateView, VideoChoiceResponse } from "../wire/generated";

export type PickFlow =
  | { step: "idle" }
  | { step: "resolving"; song: OnlineSongHit }
  | { step: "choosing"; song: OnlineSongHit; candidates: VideoCandidateView[] }
  | { step: "queuing"; song: OnlineSongHit; pickId: string }
  | { step: "failed"; song: OnlineSongHit; message: string };

export type PickEvent =
  | { type: "choose"; song: OnlineSongHit }
  | { type: "resolved"; songKey: string; response: VideoChoiceResponse }
  | { type: "resolveFailed"; songKey: string }
  | { type: "tap"; pickId: string }
  | { type: "replied"; pickId: string; outcome: Outcome }
  | { type: "cancel" };

/** What the flow wants done next. The component performs it and feeds the result back as an event. */
export type PickTask =
  | { task: "fetchVideoChoice"; songKey: string }
  | { task: "queuePick"; pickId: string }
  | null;

export function pickReducer(flow: PickFlow, ev: PickEvent): [PickFlow, PickTask] {
  // TODO: transitions per the diagram above. Events whose songKey/pickId don't match the current flow are no-ops.
  //       'official' goes straight to queuing: the spec only asks the singer when no official video exists.
  void flow; void ev;
  throw new Error("not implemented");
}
