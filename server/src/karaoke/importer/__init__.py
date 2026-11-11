"""v1 importer. Runs inside the server process, so the library keeps exactly one writer (the Preparer).

Flow (spec "Import the v1 library"):

  1. plan(limit=20)   Read v1's saved state for play counts (read-only) and pick the top N v1 song folders not yet
                      planned. For each: clean the v1 video title, catalog.search -> top song result -> proposed
                      SongMeta; catalog.resolve_video -> official video or none. Write each proposal to the plan
                      file as soon as it is matched.
  2. review           The /import page shows every proposal: v1 title, matched title, artist, video thumbnail.
                      The user confirms, corrects (search + pick, same flow as the phone), or skips each one.
                      Nothing is imported without a decision: matching was wrong 2 times in 20.
  3. run()            For each confirmed item whose final song id is not in the library:
                        official video found -> PrepRequest(meta, FromYouTube())   (full 25 s preparation)
                        else                 -> PrepRequest(meta, FromV1Files(...)) (reuse v1 video + stems,
                                                                                     redo lyrics)
                      Submitted as the 'import' lane demand, which never delays party songs.
  4. second run       plan(limit=None) extends the same plan file with the remaining ~468 songs.

Idempotency: the plan file is keyed by v1 folder name; decisions persist across restarts; run() skips items
whose song id the library already has. The importer never deletes or writes v1 files.

v1 is accessed only through V1Source, which is given the v1 folder path as configuration at runtime. No v1 code
is imported and no v1 path is written into this repository.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from karaoke.core import SongId, SongMeta
from karaoke.songs.catalog import Catalog, PickId, VideoResolution
from karaoke.songs.library import Library
from karaoke.songs.prepare import Preparer
from karaoke.vocab import ImportDecision


@dataclass(frozen=True, slots=True)
class V1Song:
    folder: Path
    raw_title: str
    play_count: int
    video: Path
    instrumental: Path
    vocals: Path


class V1Source:
    """Read-only view of a v1 install. Tolerant parser: v1 is not a contract, so anything unexpected becomes
    a skipped item with a reason, never a crash."""

    def __init__(self, root: Path) -> None:
        raise NotImplementedError

    def songs_by_play_count(self) -> list[V1Song]:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class PlanItem:
    v1: V1Song
    proposed: SongMeta | None
    video: VideoResolution | None
    final: SongMeta | None
    """Set when confirmed or corrected. final.id is the chosen video's id: the official video if found,
    otherwise the id of the v1 video itself as found by video search and confirmed by the user."""
    decision: ImportDecision


class ImportService:
    def __init__(self, v1: V1Source, plan_path: Path, catalog: Catalog, library: Library, preparer: Preparer) -> None:
        raise NotImplementedError

    async def plan(self, limit: int | None) -> None:
        raise NotImplementedError

    def items(self) -> list[PlanItem]:
        raise NotImplementedError

    def decide(self, v1_folder: str, decision: Literal["confirm", "skip", "correct"], pick: PickId | None) -> None:
        """Persist immediately (tmp + os.replace), so a stopped review resumes where it was."""
        raise NotImplementedError

    def run(self) -> None:
        """preparer.set_demand('import', [...confirmed or corrected, final.id not in library...]).
        Progress is not tracked here: the review page derives 'imported' from Library.has and live progress
        from Preparer.board(), so there is no importer-side copy of either to fall out of sync."""
        raise NotImplementedError
