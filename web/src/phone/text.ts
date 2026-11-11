// User-facing words for every closed vocabulary. Each table is a Record over the GENERATED union, so adding a
// member in server/src/karaoke/vocab.py breaks this file's compile until it gets a label. No hand-synced lists.

import type { FailReason, PrepStage, RejectReason } from "../wire/generated";

export const rejectText: Record<RejectReason, string> = {
  awaiting_restart_choice: "Choose to keep or start a new queue first",
  already_resolved: "Someone already answered",
  stale_play: "That song already changed",
  unknown_entry: "That song was already moved or removed",
  nothing_playing: "Nothing is playing",
  invalid_value: "That value is out of range",
  unknown_singer: "Enter your name first",
  pick_expired: "Please search again",
};

export const stageText: Record<PrepStage, string> = {
  waiting: "In line to prepare",
  downloading: "Downloading",
  separating: "Separating vocals",
  aligning: "Timing lyrics",
  ready: "Ready",
  failed: "Can't prepare",
};

export const failText: Record<FailReason, string> = {
  cant_download: "Can't download",
  video_unavailable: "Video unavailable",
  processing_crashed: "Preparation failed",
  disk_full: "Laptop disk is full",
};
