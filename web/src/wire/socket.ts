// The one client for the party WebSocket, shared by the TV and the phone. Pages never touch WebSocket directly
// (eslint no-restricted-globals on `WebSocket` outside this file).
//
// The latest server snapshot is the truth. The socket keeps nothing else. Reconnect means resend hello and
// receive a fresh snapshot. No patches and no optimistic edits, so there is nothing to reconcile after a drop.

import { PROTOCOL } from "./generated";
import type {
  ClientMessage,
  Outcome,
  PhoneCommand,
  PhoneView,
  ServerMessage,
  TvCommand,
  TvView,
} from "./types";

export function assertNever(x: never): never {
  throw new Error(`unhandled variant: ${JSON.stringify(x)}`);
}

export interface ClockSample {
  playId: number;
  positionS: number;
  paused: boolean;
  receivedAtMs: number;
}

export type Link = "connecting" | "open" | "superseded";

export interface PartySocket<View, Command> {
  /** Latest snapshot, or null before the first one. */
  view: () => View | null;
  subscribe: (listener: () => void) => () => void;
  /** Resolves with the server's verdict. Rejects only on disconnect. */
  send(command: Command): Promise<Outcome>;
  /** Phones only: latest relayed TV clock, for the progress bar. */
  clock(): ClockSample | null;
  /** TV only: telemetry, not a command, so there is no reply. */
  reportClock(playId: number, positionS: number, paused: boolean): void;
  link: () => Link;
  /** Phones only: the singer id the server assigned this connection, from its "you" message. */
  me: () => string | null;
}

export interface PhoneIdentityHello {
  browserId: string;
  name: string;
}

const SERVER_KINDS: ReadonlySet<string> = new Set<ServerMessage["kind"]>([
  "serverHello",
  "you",
  "reply",
  "phoneView",
  "tvView",
  "clock",
  "superseded",
]);

/** The wire boundary. The server serializes from the same contract the types come from, so the kind check is
 *  what separates a contract message from garbage. A different contract is caught by the protocol hash. */
function parseServerMessage(data: unknown): ServerMessage | null {
  if (typeof data !== "string") return null;
  let raw: unknown;
  try {
    raw = JSON.parse(data);
  } catch {
    return null;
  }
  if (typeof raw !== "object" || raw === null || !("kind" in raw) || typeof raw.kind !== "string") return null;
  if (!SERVER_KINDS.has(raw.kind)) return null;
  return raw as ServerMessage;
}

/** A server serving a stale build would otherwise reload the page forever. */
function reloadOnce(serverProtocol: string): void {
  const key = "karaoke.reloadedFor";
  try {
    if (sessionStorage.getItem(key) === serverProtocol) return;
    sessionStorage.setItem(key, serverProtocol);
  } catch {
    return;
  }
  location.reload();
}

interface Pending {
  resolve(outcome: Outcome): void;
  reject(error: Error): void;
}

function connect<View extends { rev: number }, Command>(options: {
  hello: () => ClientMessage;
  wrap: (requestId: number, command: Command) => ClientMessage;
  pickView: (msg: ServerMessage) => View | null;
}): PartySocket<View, Command> {
  const listeners = new Set<() => void>();
  const pending = new Map<number, Pending>();
  let ws: WebSocket | null = null;
  let current: View | null = null;
  let acceptAnyRev = true;
  let clockSample: ClockSample | null = null;
  let link: Link = "connecting";
  let me: string | null = null;
  let nextRequestId = 1;
  let backoffMs = 500;

  const notify = (): void => {
    for (const l of listeners) l();
  };

  const setLink = (next: Link): void => {
    if (link !== next) {
      link = next;
      notify();
    }
  };

  const failPending = (): void => {
    for (const p of pending.values()) p.reject(new Error("disconnected"));
    pending.clear();
  };

  const open = (): void => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${proto}://${location.host}/ws`);
    ws = socket;
    socket.onopen = () => {
      backoffMs = 500;
      // A restarted server starts its rev counter again, so the first snapshot after a hello always wins.
      acceptAnyRev = true;
      socket.send(JSON.stringify(options.hello()));
    };
    socket.onmessage = (event) => {
      const msg = parseServerMessage(event.data);
      if (msg === null) return;
      switch (msg.kind) {
        case "serverHello":
          if (msg.protocol !== PROTOCOL) reloadOnce(msg.protocol);
          return;
        case "you":
          if (me !== msg.singerId) {
            me = msg.singerId;
            notify();
          }
          return;
        case "phoneView":
        case "tvView": {
          const view = options.pickView(msg);
          if (view === null) return;
          if (acceptAnyRev || current === null || view.rev > current.rev) {
            acceptAnyRev = false;
            current = view;
            link = "open";
            notify();
          }
          return;
        }
        case "reply": {
          const p = pending.get(msg.requestId);
          pending.delete(msg.requestId);
          p?.resolve(msg.outcome);
          return;
        }
        case "clock":
          clockSample = {
            playId: msg.playId,
            positionS: msg.positionS,
            paused: msg.paused,
            receivedAtMs: performance.now(),
          };
          notify();
          return;
        case "superseded":
          link = "superseded";
          socket.onclose = null;
          socket.close();
          failPending();
          notify();
          return;
        default:
          assertNever(msg);
      }
    };
    socket.onclose = () => {
      ws = null;
      failPending();
      setLink("connecting");
      window.setTimeout(open, backoffMs);
      backoffMs = Math.min(backoffMs * 2, 5000);
    };
  };

  open();

  return {
    view: () => current,
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    send(command) {
      return new Promise<Outcome>((resolve, reject) => {
        if (ws === null || ws.readyState !== WebSocket.OPEN) {
          reject(new Error("disconnected"));
          return;
        }
        const requestId = nextRequestId++;
        pending.set(requestId, { resolve, reject });
        ws.send(JSON.stringify(options.wrap(requestId, command)));
      });
    },
    clock: () => clockSample,
    reportClock(playId, positionS, paused) {
      if (ws?.readyState === WebSocket.OPEN) {
        const msg: ClientMessage = { kind: "clock", playId, positionS, paused };
        ws.send(JSON.stringify(msg));
      }
    },
    link: () => link,
    me: () => me,
  };
}

export function connectPhone(identity: () => PhoneIdentityHello): PartySocket<PhoneView, PhoneCommand> {
  return connect<PhoneView, PhoneCommand>({
    hello: () => ({ kind: "phoneHello", ...identity() }),
    wrap: (requestId, command) => ({ kind: "phoneCommand", requestId, command }),
    pickView: (msg) => (msg.kind === "phoneView" ? msg.view : null),
  });
}

export function connectTv(): PartySocket<TvView, TvCommand> {
  return connect<TvView, TvCommand>({
    hello: () => ({ kind: "tvHello" }),
    wrap: (requestId, command) => ({ kind: "tvCommand", requestId, command }),
    pickView: (msg) => (msg.kind === "tvView" ? msg.view : null),
  });
}
