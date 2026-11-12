import { describe, expect, it } from "vitest";
import type { OnlineSongHit } from "../wire/types";
import { pickReducer, type PickFlow } from "./pickVideo";

const song: OnlineSongHit = {
  onlineKey: "k1",
  title: "Song",
  artist: "Artist",
  artistId: "a1",
  durationS: 200,
  thumbnailUrl: "",
};
const candidate = { pickId: "p2", title: "v", channel: "c", thumbnailUrl: "", durationS: 1 };

describe("pick-a-video flow", () => {
  it("queues the official video without asking", () => {
    const [resolving, fetch] = pickReducer({ step: "idle" }, { type: "choose", song });
    expect(fetch).toEqual({ task: "fetchVideoChoice", songKey: "k1" });
    const [queuing, task] = pickReducer(resolving, { type: "resolved", songKey: "k1", response: { kind: "official", pickId: "p1" } });
    expect(queuing).toMatchObject({ step: "queuing", pickId: "p1", candidates: null });
    expect(task).toEqual({ task: "queuePick", pickId: "p1" });
    expect(pickReducer(queuing, { type: "replied", pickId: "p1", outcome: { kind: "accepted" } })[0]).toEqual({ step: "idle" });
  });

  it("asks the singer when there is no official video", () => {
    const resolving: PickFlow = { step: "resolving", song };
    const [choosing] = pickReducer(resolving, { type: "resolved", songKey: "k1", response: { kind: "choose", candidates: [candidate] } });
    expect(choosing.step).toBe("choosing");
    const [queuing, task] = pickReducer(choosing, { type: "tap", pickId: "p2" });
    expect(queuing).toMatchObject({ step: "queuing", pickId: "p2" });
    expect(task).toEqual({ task: "queuePick", pickId: "p2" });
  });

  it("ignores a late answer for a cancelled song", () => {
    const [idle] = pickReducer({ step: "resolving", song }, { type: "cancel" });
    expect(pickReducer(idle, { type: "resolved", songKey: "k1", response: { kind: "official", pickId: "p1" } })).toEqual([idle, null]);
  });

  it("reports a rejection in words", () => {
    const flow: PickFlow = { step: "queuing", song, pickId: "p1", candidates: null };
    const [failed] = pickReducer(flow, { type: "replied", pickId: "p1", outcome: { kind: "rejected", reason: "pick_expired" } });
    expect(failed).toMatchObject({ step: "failed", message: "Please search again" });
  });
});
