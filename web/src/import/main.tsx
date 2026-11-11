// Import review page (import.html), opened on the laptop. HTTP only (no party socket): the importer is not part of
// the party.
//
//   [Match next 20] -> POST /api/import/plan?limit=20         [Match the rest] -> POST /api/import/plan
//   table, one row per v1 song (polls GET /api/import every 2 s while matching or importing):
//     v1 title | play count | proposed title / artist | video thumbnail (official) or "Reuse v1 video" |
//     [Confirm] [Correct...] [Skip] | status: imported / preparing stage / failed
//   [Correct...] opens the same search + video picker components as the phone (shared from ../phone), and posts
//     POST /api/import/decide { decision: "correct", pickId }
//   [Import confirmed] -> POST /api/import/run    (disabled while any row is still 'proposed' in the current batch)

import type { ImportPlanView } from "../wire/generated";

export function ImportPage(): JSX.Element {
  void (null as unknown as ImportPlanView);
  throw new Error("not implemented");
}
