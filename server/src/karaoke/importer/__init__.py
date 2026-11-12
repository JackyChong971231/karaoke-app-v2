"""v1 importer. Runs inside the server process, so the library keeps exactly one writer (the Preparer).

Flow (spec "Import the v1 library"):

  1. plan(limit=20)   Read v1's saved state for play counts (read-only) and pick the top N v1 song folders not yet
                      planned. For each: clean the v1 video title, catalog.search -> top song result;
                      catalog.resolve_video -> the official video if the strict rule finds one, else the v1 video
                      itself (its id from meta.json). Write each proposal to the plan file as soon as it is matched.
  2. review           The /import page shows every proposal. The user confirms, corrects (search + pick, same
                      flow as the phone), or skips each one. Nothing is imported without a decision: matching was
                      wrong 2 times in 20.
  3. run()            For each confirmed or corrected item whose final song id is not in the library:
                        final id is the v1 video -> PrepRequest(meta, FromV1Files(...)) (reuse v1 video + stems,
                                                                                        redo lyrics)
                        any other video          -> PrepRequest(meta, FromYouTube())    (full preparation)
                      Submitted as the 'import' lane demand, which never delays party songs.
  4. second run       plan(limit=None) extends the same plan file with the remaining songs.

Idempotency: the plan file is keyed by v1 folder name; decisions persist across restarts; run() skips items
whose song id the library already has. The importer never deletes or writes v1 files.

v1 is accessed only through V1Source, which is given the v1 folder path as configuration at runtime. No v1 code
is imported and no v1 path is written into this repository.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, cast

from karaoke.core import ArtistId, ArtistRef, SongId, SongMeta
from karaoke.songs.catalog import (
    Catalog, ChooseVideo, OfficialVideo, OnlineKey, OnlineUnavailable, PickId, VideoCandidate,
)
from karaoke.songs.library import Library, search_key
from karaoke.songs.prepare import FromV1Files, FromYouTube, PrepRequest, Preparer
from karaoke.vocab import ImportDecision

_VIDEO_ID = re.compile(r"(?:[?&]v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})")
_NOISE = re.compile(
    r"\[[^\]]*\]|【[^】]*】|『[^』]*』|\([^)]*(official|video|mv|lyrics?|live|hd|karaoke)[^)]*\)"
    r"|(official|music video|mv|歌詞|歌词|lyrics?|karaoke|伴奏|伴唱|動態|字幕)\S*|…|\bby\b|電影主題曲|电影主題曲", re.I)


def video_id_from_url(url: str) -> SongId | None:
    m = _VIDEO_ID.search(url or "")
    return SongId(m.group(1)) if m else None


def clean_title(raw: str) -> str:
    """A v1 video title as a search query: tags like [MV], 【動態歌詞】 and (Official Video) removed."""
    return re.sub(r"\s+", " ", _NOISE.sub(" ", raw)).strip(" -|｜")


@dataclass(frozen=True, slots=True)
class V1Song:
    folder: Path
    raw_title: str
    play_count: int
    video: Path
    instrumental: Path
    vocals: Path
    video_id: SongId | None
    """From meta.json's URL. None for the few v1 folders without one."""


class V1Source:
    """Read-only view of a v1 install. Tolerant parser: v1 is not a contract, so anything unexpected becomes
    a skipped item with a reason, never a crash."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def songs_by_play_count(self) -> list[V1Song]:
        counts = _counts(self.root / "Karaoke_state.json")
        data = self.root / "karaoke_data"
        songs = [self._song(d, counts) for d in sorted(data.iterdir()) if d.is_dir()] if data.is_dir() else []
        return sorted(songs, key=lambda s: -s.play_count)

    @staticmethod
    def _song(d: Path, counts: dict[str, int]) -> V1Song:
        meta = _read_json(d / "meta.json")
        # v1 named each folder "<channel>_<video title>" and counted plays by video title.
        title = meta.get("title") if isinstance(meta.get("title"), str) else None
        if not title:
            title = next((t for t in counts if d.name.endswith("_" + t)), d.name.split("_", 1)[-1])
        return V1Song(d, title, counts.get(title, 0), d / "video.mp4", d / "instrumental.wav", d / "vocals.wav",
                      video_id_from_url(str(meta.get("url") or "")))


def _read_json(p: Path) -> dict[str, Any]:
    try:
        d = json.loads(p.read_text("utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _counts(p: Path) -> dict[str, int]:
    raw = _read_json(p).get("song_counts")
    if not isinstance(raw, dict):
        return {}
    return {str(k): int(v) for k, v in raw.items() if isinstance(v, int)}


@dataclass(frozen=True, slots=True)
class PlanItem:
    v1: V1Song
    proposed: SongMeta | None
    """The matched song on the video it would use: the official video if the strict rule found one,
    otherwise the v1 video itself."""
    final: SongMeta | None
    """Set when confirmed or corrected."""
    decision: ImportDecision
    note: str | None = None
    """Why there is no proposal, for the review page."""

    @property
    def reuse_v1_video(self) -> bool:
        chosen = self.final or self.proposed
        return chosen is not None and chosen.id == self.v1.video_id

    def request(self) -> PrepRequest | None:
        if self.decision not in ("confirmed", "corrected") or self.final is None:
            return None
        if self.reuse_v1_video:
            return PrepRequest(self.final, FromV1Files(self.v1.video, self.v1.instrumental, self.v1.vocals))
        return PrepRequest(self.final, FromYouTube())


class ImportService:
    def __init__(self, v1: V1Source, plan_path: Path, catalog: Catalog, library: Library, preparer: Preparer) -> None:
        self._v1 = v1
        self._plan_path = plan_path
        self._catalog = catalog
        self._library = library
        self._preparer = preparer
        self._items: dict[str, PlanItem] = _load(plan_path)

    async def plan(self, limit: int | None) -> None:
        """Match the next `limit` most-played v1 songs that are not planned yet (None: all of them)."""
        fresh = [s for s in self._v1.songs_by_play_count() if s.folder.name not in self._items]
        for song in fresh[:limit]:
            self._items[song.folder.name] = await self._propose(song)
            self._save()

    async def _propose(self, song: V1Song) -> PlanItem:
        missing = [p.name for p in (song.video, song.instrumental, song.vocals) if not p.is_file()]
        if missing:
            return PlanItem(song, None, None, "skipped", f"v1 files missing: {', '.join(missing)}")
        if song.video_id:
            record = self._library.get(song.video_id)
            if record:
                return PlanItem(song, record.meta, None, "proposed", "already in the library")
            key = await self._catalog.identify(song.video_id)
            if key:
                return await self._propose_for(song, key)
        result = await self._catalog.search(clean_title(song.raw_title))
        if isinstance(result.online, OnlineUnavailable):
            return PlanItem(song, None, None, "proposed", f"online search unavailable: {result.online.reason}")
        # Search hides online copies of library songs, so a song already in the library must be taken from the
        # library hits, or the top online result is a different song by the same artist.
        named = next((h.song for h in result.library if search_key(h.song.title) in search_key(song.raw_title)), None)
        if named or not result.online:
            hit = named or (result.library[0].song if result.library else None)
            return PlanItem(song, hit, None, "proposed", "already in the library" if hit else "no song found")
        return await self._propose_for(song, result.online[0].key)

    async def _propose_for(self, song: V1Song, key: OnlineKey) -> PlanItem:
        match await self._catalog.resolve_video(key):
            case OfficialVideo(pick=pick):
                return PlanItem(song, self._catalog.pick(pick), None, "proposed")
            case ChooseVideo(candidates=candidates):
                video = song.video_id or _same_video(candidates, song.raw_title)
                if video is None:
                    return PlanItem(song, None, None, "proposed", "v1 video id unknown; pick its video")
                return PlanItem(song, self._catalog.pick(self._catalog.pick_video(key, video)), None, "proposed")
        raise AssertionError("unreachable")

    def items(self) -> list[PlanItem]:
        return sorted(self._items.values(), key=lambda i: -i.v1.play_count)

    def decide(self, v1_folder: str, decision: Literal["confirm", "skip", "correct"], pick: PickId | None) -> None:
        """Persist immediately (tmp + os.replace), so a stopped review resumes where it was.
        Raises KeyError for an unknown item, LookupError for an expired pick, ValueError for confirming
        an item with no proposal."""
        item = self._items[v1_folder]
        if decision == "skip":
            item = replace(item, final=None, decision="skipped")
        elif decision == "confirm":
            if item.proposed is None:
                raise ValueError("nothing to confirm: correct or skip this item")
            item = replace(item, final=item.proposed, decision="confirmed")
        else:
            meta = self._catalog.pick(pick) if pick else None
            if meta is None:
                raise LookupError("pick expired: search again")
            item = replace(item, final=meta, decision="corrected")
        self._items[v1_folder] = item
        self._save()

    def run(self) -> None:
        """preparer.set_demand('import', [...confirmed or corrected, final.id not in library...]).
        Progress is not tracked here: the review page derives 'imported' from Library.has and live progress
        from Preparer.board(), so there is no importer-side copy of either to fall out of sync."""
        requests = [r for item in self.items() if (r := item.request()) and not self._library.has(r.song.id)]
        self._preparer.set_demand("import", requests)

    def _save(self) -> None:
        tmp = self._plan_path.with_name(self._plan_path.name + ".part")
        body = {"version": 1, "items": [_item_json(i) for i in self._items.values()]}
        tmp.write_text(json.dumps(body, ensure_ascii=False, indent=1), "utf-8")
        os.replace(tmp, self._plan_path)


def _same_video(candidates: tuple[VideoCandidate, ...], raw_title: str) -> SongId | None:
    """v1 stored titles cut with '…', so a prefix match finds the video v1 downloaded."""
    def key(t: str) -> str:
        return unicodedata.normalize("NFKC", t).casefold().split("…")[0].strip()
    want = key(raw_title)
    return next((c.video_id for c in candidates if want and key(c.title).startswith(want)), None)


def _meta_json(m: SongMeta | None) -> dict[str, Any] | None:
    if m is None:
        return None
    return {"id": m.id, "title": m.title, "artist": {"id": m.artist.id, "name": m.artist.name},
            "duration_s": m.duration_s}


def _meta(d: dict[str, Any] | None) -> SongMeta | None:
    if not d:
        return None
    a = d["artist"]
    return SongMeta(SongId(d["id"]), d["title"], ArtistRef(ArtistId(a["id"]), a["name"]), float(d["duration_s"]))


def _item_json(i: PlanItem) -> dict[str, Any]:
    v = i.v1
    return {
        "folder": str(v.folder), "raw_title": v.raw_title, "play_count": v.play_count, "video": str(v.video),
        "instrumental": str(v.instrumental), "vocals": str(v.vocals), "video_id": v.video_id,
        "proposed": _meta_json(i.proposed), "final": _meta_json(i.final), "decision": i.decision, "note": i.note,
    }


def _load(path: Path) -> dict[str, PlanItem]:
    items: dict[str, PlanItem] = {}
    for d in _read_json(path).get("items") or []:
        v1 = V1Song(Path(d["folder"]), d["raw_title"], int(d["play_count"]), Path(d["video"]),
                    Path(d["instrumental"]), Path(d["vocals"]), d.get("video_id"))
        items[v1.folder.name] = PlanItem(v1, _meta(d.get("proposed")), _meta(d.get("final")),
                                         cast(ImportDecision, d["decision"]), d.get("note"))
    return items
