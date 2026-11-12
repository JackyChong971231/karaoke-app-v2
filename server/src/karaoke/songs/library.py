"""The song folders on disk. The folders are the source of truth; index.sqlite is derived.

    <library root>/                 chosen by the user; open() refuses a path inside a cloud-synced folder
      index.sqlite                  DERIVED. Rebuilt from song.json files whenever it disagrees with the folder set.
      .staging/<video id>/          in-progress preparations, resumable stage by stage (see prepare/_pipeline.py)
      <video id>/
        song.json                   SongRecord (title, artist + every known name, duration, language, source, lyrics source)
        video.mp4                   <= 1080p, no audio track
        instrumental.opus           160 kbit/s
        vocals.opus
        lyrics.json                 karaoke.contract.LyricsDoc (the TV reads it as-is)

A song is in the library iff its folder exists under the root (not .staging). `install` is the only way
a folder gets there, and it moves a complete staging folder with one os.replace, so "folder exists"
implies "every file exists".

Only this process writes the library. The importer runs inside the server and goes through `install` too.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
import time
import unicodedata
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import cast, get_args

from opencc import OpenCC

from karaoke.core import ArtistId, ArtistRef, SongId, SongMeta
from karaoke.vocab import LyricsSource, MediaFile

SONG_FILES: tuple[MediaFile, ...] = get_args(MediaFile)
STAGING = ".staging"
STALE_STAGING_S = 7 * 24 * 3600

_CLOUD_MARKERS = ("onedrive", "dropbox", "google drive", "googledrive", "icloud", "icloudrive", "box sync")


class CloudSyncedRoot(ValueError):
    """The chosen library folder is inside a cloud-synced folder (spec: local disk only)."""


class IncompleteSong(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SongRecord:
    """Contents of song.json."""

    meta: SongMeta
    artist_names: tuple[str, ...]
    """Every spelling seen for meta.artist.id (e.g. 陳奕迅, Eason Chan). Merged across songs in the index."""
    alt_titles: tuple[str, ...]
    """zh_TW and en titles, for search."""
    language: str
    lyrics_source: LyricsSource
    source_url: str

    def to_json(self) -> dict[str, object]:
        m = self.meta
        return {
            "id": m.id, "title": m.title, "artist": {"id": m.artist.id, "name": m.artist.name},
            "duration_s": m.duration_s, "artist_names": list(self.artist_names),
            "alt_titles": list(self.alt_titles), "language": self.language,
            "lyrics_source": self.lyrics_source, "source_url": self.source_url,
        }

    @staticmethod
    def from_json(d: dict) -> SongRecord:  # type: ignore[type-arg]
        a = d["artist"]
        return SongRecord(
            meta=SongMeta(SongId(d["id"]), d["title"], ArtistRef(ArtistId(a["id"]), a["name"]), float(d["duration_s"])),
            artist_names=tuple(d.get("artist_names") or (a["name"],)),
            alt_titles=tuple(d.get("alt_titles") or ()),
            language=d.get("language", ""),
            lyrics_source=cast(LyricsSource, d["lyrics_source"]),
            source_url=d.get("source_url", ""),
        )


@dataclass(frozen=True, slots=True)
class ArtistEntry:
    ref: ArtistRef
    names: tuple[str, ...]
    songs: tuple[SongMeta, ...]


@lru_cache(maxsize=1)
def _t2s() -> OpenCC:
    return OpenCC("t2s")


def search_key(text: str) -> str:
    """Case-, width-, and script-insensitive form: 陳奕迅, 陈奕迅 and ｅａｓｏｎ all meet."""
    return str(_t2s().convert(unicodedata.normalize("NFKC", text).casefold()))


def cloud_sync_reason(root: Path) -> str | None:
    resolved = root.resolve()
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        synced = os.environ.get(var)
        if synced and resolved.is_relative_to(Path(synced).resolve()):
            return f"inside {var} ({synced})"
    for part in resolved.parts:
        if any(part.casefold().startswith(m) for m in _CLOUD_MARKERS):
            return f"inside a cloud-synced folder ({part})"
    return None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS songs (id TEXT PRIMARY KEY, artist_id TEXT NOT NULL, title_key TEXT NOT NULL, record TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS artist_names (artist_id TEXT NOT NULL, name TEXT NOT NULL, key TEXT NOT NULL,
                                         PRIMARY KEY (artist_id, name));
"""


class Library:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._db: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    def open(self) -> None:
        """Boot. Verify root is a local, non-synced folder. Rebuild index.sqlite from song.json files
        if the set of song folders differs from the index. Delete .staging folders untouched for 7 days;
        younger ones are resumed when their song is demanded again."""
        reason = cloud_sync_reason(self.root)
        if reason:
            raise CloudSyncedRoot(f"Library folder {self.root} is {reason}. Choose a folder on a local disk.")
        (self.root / STAGING).mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.root / "index.sqlite", check_same_thread=False, isolation_level=None)
        self._db.executescript(_SCHEMA)
        self._drop_stale_staging()
        on_disk = set(self._folder_ids())
        indexed = {r[0] for r in self._q("SELECT id FROM songs")}
        if on_disk != indexed:
            self._rebuild(on_disk)

    def _folder_ids(self) -> list[SongId]:
        return [SongId(p.name) for p in self.root.iterdir()
                if p.is_dir() and not p.name.startswith(".") and (p / "song.json").exists()]

    def _drop_stale_staging(self) -> None:
        cutoff = time.time() - STALE_STAGING_S
        for d in (self.root / STAGING).iterdir():
            if not d.is_dir():
                continue
            newest = max([d.stat().st_mtime, *(f.stat().st_mtime for f in d.rglob("*"))])
            if newest < cutoff:
                shutil.rmtree(d, ignore_errors=True)

    def _rebuild(self, ids: Collection[SongId]) -> None:
        with self._lock:
            db = self._conn()
            db.execute("BEGIN")
            db.execute("DELETE FROM songs")
            db.execute("DELETE FROM artist_names")
            for song in ids:
                record = self._read_record(song)
                if record:
                    self._upsert(db, record)
            db.execute("COMMIT")

    def _read_record(self, song: SongId) -> SongRecord | None:
        try:
            return SongRecord.from_json(json.loads((self.root / song / "song.json").read_text("utf-8")))
        except (OSError, ValueError, KeyError):
            return None

    @staticmethod
    def _upsert(db: sqlite3.Connection, r: SongRecord) -> None:
        titles = " ".join(search_key(t) for t in (r.meta.title, *r.alt_titles))
        db.execute("INSERT OR REPLACE INTO songs VALUES (?, ?, ?, ?)",
                   (r.meta.id, r.meta.artist.id, titles, json.dumps(r.to_json(), ensure_ascii=False)))
        for name in {r.meta.artist.name, *r.artist_names}:
            db.execute("INSERT OR IGNORE INTO artist_names VALUES (?, ?, ?)", (r.meta.artist.id, name, search_key(name)))

    def _conn(self) -> sqlite3.Connection:
        if self._db is None:
            raise RuntimeError("Library.open() was not called")
        return self._db

    def _q(self, sql: str, args: tuple[object, ...] = ()) -> list[tuple]:  # type: ignore[type-arg]
        with self._lock:
            return self._conn().execute(sql, args).fetchall()

    # ---- read ----
    def get(self, song: SongId) -> SongRecord | None:
        rows = self._q("SELECT record FROM songs WHERE id = ?", (song,))
        return SongRecord.from_json(json.loads(rows[0][0])) if rows else None

    def has(self, song: SongId) -> bool:
        return (self.root / song / "song.json").exists()

    def search(self, text: str, limit: int = 30) -> list[SongRecord]:
        """Every query word must appear in a title, an alt title, or any spelling of the artist.
        Substring match rather than FTS5: CJK text has no word boundaries for a tokenizer to find."""
        words = search_key(text).split()
        if not words:
            return []
        haystack = "(s.title_key || ' ' || a.keys)"
        where = " AND ".join(f"instr({haystack}, ?) > 0" for _ in words)
        rows = self._q(
            "SELECT s.record FROM songs s JOIN (SELECT artist_id, group_concat(key, ' ') AS keys "
            f"FROM artist_names GROUP BY artist_id) a USING (artist_id) WHERE {where} LIMIT ?",
            (*words, limit),
        )
        return [SongRecord.from_json(json.loads(r[0])) for r in rows]

    def artist(self, artist: ArtistId) -> ArtistEntry | None:
        songs = [SongRecord.from_json(json.loads(r[0]))
                 for r in self._q("SELECT record FROM songs WHERE artist_id = ?", (artist,))]
        if not songs:
            return None
        names = tuple(sorted(r[0] for r in self._q("SELECT name FROM artist_names WHERE artist_id = ?", (artist,))))
        songs.sort(key=lambda r: r.meta.title)
        return ArtistEntry(songs[0].meta.artist, names, tuple(r.meta for r in songs))

    def random_pick(self, avoid: Collection[SongId], recent: Sequence[SongId] = ()) -> SongMeta | None:
        """A random song outside `avoid`. When `avoid` covers the whole library, the song that is oldest in
        `recent` (newest first), so two songs alternate rather than one repeating."""
        rows = self._q("SELECT id, record FROM songs ORDER BY random()")
        fresh = [r for r in rows if r[0] not in avoid]
        if not fresh:
            age = {s: i for i, s in enumerate(recent)}
            fresh = sorted(rows, key=lambda r: -age.get(r[0], len(recent)))
        return SongRecord.from_json(json.loads(fresh[0][1])).meta if fresh else None

    def media_path(self, song: SongId, file: MediaFile) -> Path | None:
        """For the HTTP media route. None if not installed (never serves from .staging)."""
        if file not in SONG_FILES or song.startswith(".") or "/" in song or "\\" in song:
            return None
        p = self.root / song / file
        return p if p.is_file() else None

    def count(self) -> int:
        return int(self._q("SELECT count(*) FROM songs")[0][0])

    # ---- write (Preparer only) ----
    def staging_dir(self, song: SongId) -> Path:
        """<root>/.staging/<song>/, created if missing. Same volume as root, so install is a rename."""
        d = self.root / STAGING / song
        d.mkdir(parents=True, exist_ok=True)
        return d

    def install(self, song: SongId, record: SongRecord) -> None:
        """Atomically publish a finished staging folder. A crash before the rename leaves only staging
        (resumed later). A crash after it leaves a complete folder with a stale index, which open()
        repairs. Idempotent: if the song is already installed, the staging folder is dropped."""
        d = self.root / STAGING / song
        target = self.root / song
        if target.exists():
            shutil.rmtree(d, ignore_errors=True)
            record = self._read_record(song) or record
        else:
            missing = [f for f in SONG_FILES if not (d / f).is_file() or (d / f).stat().st_size == 0]
            if missing:
                raise IncompleteSong(f"{song}: missing {missing}")
            tmp = d / "song.json.part"
            tmp.write_text(json.dumps(record.to_json(), ensure_ascii=False, indent=1), "utf-8")
            os.replace(tmp, d / "song.json")
            _replace_dir(d, target)
        with self._lock:
            self._upsert(self._conn(), record)


def _replace_dir(src: Path, dst: Path) -> None:
    # Antivirus and the search indexer briefly hold handles on freshly written files, which makes a
    # directory rename fail with a sharing violation on Windows.
    for attempt in range(20):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.25)
