// The one client for the party WebSocket, shared by the TV and the phone. Pages never touch WebSocket directly
// (eslint no-restricted-globals on `WebSocket` outside this file).
//
// Contract: the latest server snapshot is the truth. The socket keeps nothing else. Reconnect = resend hello,
// receive a fresh snapshot. No patches, no optimistic edits, so there is nothing to reconcile after a drop.

import type { ClientMessage, Outcome, PhoneCommand, PhoneView, ServerMessage, TvCommand, TvView } from "./generated";

export function assertNever(x: never): never {
  throw new Error(`unhandled variant: ${JSON.stringify(x)}`);
}

type Role =
  | { role: "phone"; singerId: string; name: string }
  | { role: "tv" };

type ViewFor<R extends Role> = R extends { role: "phone" } ? PhoneView : TvView;
type CommandFor<R extends Role> = R extends { role: "phone" } ? PhoneCommand : TvCommand;

export interface ClockSample { playId: number; positionS: number; paused: boolean; receivedAtMs: number }

export interface PartySocket<R extends Role> {
  /** Latest snapshot, or null before the first one. */
  view(): ViewFor<R> | null;
  subscribe(listener: () => void): () => void;
  /** Resolves with the server's verdict. Rejects only on disconnect (the UI shows "reconnecting"). */
  send(command: CommandFor<R>): Promise<Outcome>;
  /** Phones only: latest relayed TV clock, for the progress bar. */
  clock(): ClockSample | null;
  /** TV only: telemetry, not a command; no reply. */
  reportClock(playId: number, positionS: number, paused: boolean): void;
  connected(): boolean;
}

export function connectParty<R extends Role>(hello: R): PartySocket<R> {
  // TODO pseudocode:
  //   open ws://<host>/ws; on open send hello (phoneHello | tvHello)
  //   on message: parse as ServerMessage; switch (msg.kind) {
  //     case "phoneView" | "tvView": keep if view.rev > current.rev; notify listeners
  //     case "reply": resolve pending[requestId]
  //     case "clock": keep sample with performance.now()
  //     case "superseded": stop reconnecting; notify (TV shows "Opened in another window")
  //     default: assertNever(msg)
  //   }
  //   on close: reject all pending; reconnect with backoff 0.5 s .. 5 s
  void (hello satisfies Role);
  throw new Error("not implemented");
}

// Exhaustiveness of incoming messages is checked here once, for both pages.
export function _exhaustive(msg: ServerMessage): void {
  switch (msg.kind) {
    case "reply": case "phoneView": case "tvView": case "clock": case "superseded": return;
    default: assertNever(msg);
  }
}

export type { ClientMessage };
