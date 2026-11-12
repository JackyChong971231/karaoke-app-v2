// Phone state, split by owner:
//
//   SERVER-OWNED (read-only here):  PhoneView snapshot (queue, now, settings, restart offer), relayed TV clock.
//   PHONE-OWNED (never sent as state): identity, pending command spinners, toasts, the drag preview, the
//                                      pick-a-video flow.
//
// No optimistic edits to server-owned state. On a LAN the reply arrives in tens of milliseconds; a spinner on the
// tapped control is cheaper than reconciling a guess with a concurrent edit from another phone.

import { createContext, useContext, useSyncExternalStore } from "react";
import { connectPhone, type Link, type PartySocket } from "../wire/socket";
import type { Outcome, PhoneCommand, PhoneView } from "../wire/types";
import { PickController } from "./pickVideo";
import { rejectText } from "./text";

export interface Identity {
  singerId: string;
  name: string;
}

const IDENTITY_KEY = "karaoke.identity";
let memoryIdentity: Identity | null = null;

function isIdentity(x: unknown): x is Identity {
  return (
    typeof x === "object" &&
    x !== null &&
    "singerId" in x &&
    typeof x.singerId === "string" &&
    x.singerId !== "" &&
    "name" in x &&
    typeof x.name === "string" &&
    x.name.trim() !== ""
  );
}

/** localStorage, with an in-memory fallback for private mode. */
export function loadIdentity(): Identity | null {
  try {
    const raw = localStorage.getItem(IDENTITY_KEY);
    if (raw === null) return memoryIdentity;
    const parsed: unknown = JSON.parse(raw);
    return isIdentity(parsed) ? parsed : memoryIdentity;
  } catch {
    return memoryIdentity;
  }
}

export function saveIdentity(id: Identity): void {
  memoryIdentity = id;
  try {
    localStorage.setItem(IDENTITY_KEY, JSON.stringify(id));
  } catch {
    // Private mode: the in-memory copy lasts for this visit.
  }
}

export function newSingerId(): string {
  return crypto.randomUUID();
}

export interface Toast {
  id: number;
  message: string;
  tone: "info" | "success" | "error";
}

export interface PhoneState {
  view: PhoneView | null;
  link: Link;
  identity: Identity;
  /** Controls showing a spinner until their reply arrives, keyed by a control id such as "skip". */
  pending: ReadonlySet<string>;
  toasts: readonly Toast[];
  /** Queue order shown while a drag-drop move is in flight, so the row does not jump back before the reply. */
  reorder: readonly number[] | null;
}

export interface PhoneStore {
  get: () => PhoneState;
  subscribe: (listener: () => void) => () => void;
  /** Send and track the spinner. A rejection shows rejectText[reason] as a toast. Null when disconnected. */
  run(
    controlId: string,
    cmd: PhoneCommand,
    opts?: { reorder?: readonly number[]; quiet?: boolean },
  ): Promise<Outcome | null>;
  /** Interpolated now-playing position: last clock sample plus elapsed time if not paused. */
  progressS(): number | null;
  toast(message: string, tone?: Toast["tone"]): void;
  rename(name: string): Promise<boolean>;
  readonly pick: PickController;
}

export function createPhoneStore(initial: Identity): PhoneStore {
  let identity = initial;
  const socket: PartySocket<PhoneView, PhoneCommand> = connectPhone(() => identity);
  const listeners = new Set<() => void>();
  let state: PhoneState = {
    view: socket.view(),
    link: socket.link(),
    identity,
    pending: new Set(),
    toasts: [],
    reorder: null,
  };
  let nextToast = 1;

  const set = (patch: Partial<PhoneState>): void => {
    state = { ...state, ...patch };
    for (const l of listeners) l();
  };

  socket.subscribe(() => {
    const view = socket.view();
    const link = socket.link();
    if (view !== state.view || link !== state.link) set({ view, link });
  });

  const toast = (message: string, tone: Toast["tone"] = "info"): void => {
    const id = nextToast++;
    set({ toasts: [...state.toasts.filter((t) => t.message !== message), { id, message, tone }].slice(-2) });
    window.setTimeout(() => { set({ toasts: state.toasts.filter((t) => t.id !== id) }); }, 2400);
  };

  const run: PhoneStore["run"] = async (controlId, cmd, opts) => {
    if (state.pending.has(controlId)) return null;
    set({
      pending: new Set([...state.pending, controlId]),
      ...(opts?.reorder ? { reorder: opts.reorder } : {}),
    });
    let outcome: Outcome | null = null;
    try {
      outcome = await socket.send(cmd);
      if (outcome.kind === "rejected" && opts?.quiet !== true) toast(rejectText[outcome.reason], "error");
    } catch {
      if (opts?.quiet !== true) toast("Not connected to the karaoke laptop", "error");
    }
    const pending = new Set(state.pending);
    pending.delete(controlId);
    set({ pending, ...(opts?.reorder ? { reorder: null } : {}) });
    return outcome;
  };

  const store: PhoneStore = {
    get: () => state,
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    run,
    progressS() {
      const now = state.view?.now;
      const clock = socket.clock();
      if (!now || clock === null || clock.playId !== now.playId) return null;
      const elapsed = clock.paused || now.paused ? 0 : (performance.now() - clock.receivedAtMs) / 1000;
      return Math.min(now.song.durationS, clock.positionS + elapsed);
    },
    toast,
    async rename(name) {
      const outcome = await run("rename", { kind: "rename", name });
      if (outcome?.kind !== "accepted") return false;
      identity = { ...identity, name };
      saveIdentity(identity);
      set({ identity });
      return true;
    },
    pick: new PickController(
      (pickId) => run(`pick:${pickId}`, { kind: "queuePick", pickId }, { quiet: true }),
      (song) => { toast(`Queued “${song.title}”`, "success"); },
    ),
  };

  window.__karaokePhone = {
    probe: () => ({
      rev: state.view?.rev ?? null,
      pickFlow: store.pick.get().step,
      pendingRequests: [...state.pending],
      singerId: identity.singerId,
    }),
  };
  return store;
}

declare global {
  interface Window {
    __karaokePhone?: { probe(): unknown };
  }
}

export const StoreContext = createContext<PhoneStore | null>(null);

export function useStore(): PhoneStore {
  const store = useContext(StoreContext);
  if (store === null) throw new Error("useStore outside <StoreContext.Provider>");
  return store;
}

/** React binding: the whole phone state, re-rendered when the snapshot or a local field changes. */
export function usePhone(): PhoneState {
  const store = useStore();
  return useSyncExternalStore(store.subscribe, store.get);
}
