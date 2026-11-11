// Phone state, split by owner:
//
//   SERVER-OWNED (read-only here):  PhoneView snapshot (queue, now, settings, restart offer), relayed TV clock.
//   PHONE-OWNED (never sent as state): identity, current screen, search text + results, pick-video flow,
//                                      drag preview, pending command spinners.
//
// No optimistic edits to server-owned state. On a LAN the reply arrives in tens of milliseconds; a spinner on the
// tapped control is cheaper than reconciling a guess with a concurrent edit from another phone.

import type { Outcome, PhoneCommand, PhoneView, SearchResponse } from "../wire/generated";
import type { PickFlow } from "./pickVideo";

export interface Identity { singerId: string; name: string }

/** localStorage, with an in-memory fallback (private mode). singerId = crypto.randomUUID() on first visit. */
export function loadIdentity(): Identity | null { throw new Error("not implemented"); }
export function saveIdentity(id: Identity): void { void id; throw new Error("not implemented"); }

export type Screen =
  | { name: "queue" }                                   // now playing + controls + queue
  | { name: "search"; query: string }
  | { name: "artist"; artistId: string }
  | { name: "settings" };                               // name, AV offset, device info

export interface PhoneLocal {
  identity: Identity | null;
  screen: Screen;
  search: { query: string; result: SearchResponse | null; loading: boolean };
  pick: PickFlow;
  /** Entry being dragged and its preview index. While set, incoming snapshots update everything except
   *  the dragged row's position; on drop the phone sends one `move { before: <entry at drop index + 1> }`. */
  drag: { entryId: number; previewIndex: number } | null;
  /** Controls showing a spinner until their reply arrives, keyed by a control id, e.g. "skip", "entry:42:remove". */
  pending: ReadonlySet<string>;
}

export interface PhoneStore {
  view(): PhoneView | null;
  local(): PhoneLocal;
  /** Send and track the spinner. A rejection shows rejectText[reason] as a toast. */
  run(controlId: string, cmd: PhoneCommand): Promise<Outcome>;
  /** Interpolated now-playing position for the progress bar: last clock sample + elapsed if not paused. */
  progressS(): number | null;
  subscribe(listener: () => void): () => void;
}

export function createPhoneStore(identity: Identity): PhoneStore { void identity; throw new Error("not implemented"); }

/** React binding: useSyncExternalStore over PhoneStore. */
export function usePhone(): PhoneStore { throw new Error("not implemented"); }
