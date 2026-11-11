"""The song folders on disk. The folders are the source of truth; index.sqlite is derived.

    <library root>/                 chosen by the user; boot refuses a path under a OneDrive/Dropbox root
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

from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from karaoke.core import ArtistId, ArtistRef, SongId, SongMeta
from karaoke.vocab import LyricsSource, MediaFile



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


@dataclass(frozen=True, slots=True)
class ArtistEntry:
    ref: ArtistRef
    names: tuple[str, ...]
    songs: tuple[SongMeta, ...]


class Library:
    def __init__(self, root: Path) -> None:
        raise NotImplementedError

    def open(self) -> None:
        """Boot. Verify root is a local, non-synced folder. Rebuild index.sqlite from song.json files
        if the set of song folders differs from the index (cheap: ~500 folders). Delete .staging
        folders untouched for 7 days; younger ones are resumed when their song is demanded again."""
        raise NotImplementedError

    # ---- read ----
    def get(self, song: SongId) -> SongRecord | None: raise NotImplementedError
    def has(self, song: SongId) -> bool: raise NotImplementedError
    def search(self, text: str, limit: int = 30) -> list[SongRecord]:
        """FTS over titles, alt titles, and every artist name. Case- and width-insensitive."""
        raise NotImplementedError
    def artist(self, artist: ArtistId) -> ArtistEntry | None: raise NotImplementedError
    def random_pick(self, avoid: Collection[SongId]) -> SongMeta | None: raise NotImplementedError
    def media_path(self, song: SongId, file: MediaFile) -> Path | None:
        """For the HTTP media route. None if not installed (never serves from .staging)."""
        raise NotImplementedError
    def count(self) -> int: raise NotImplementedError

    # ---- write (Preparer only) ----
    def staging_dir(self, song: SongId) -> Path:
        """<root>/.staging/<song>/, created if missing. Same volume as root, so install is a rename."""
        raise NotImplementedError

    def install(self, song: SongId, record: SongRecord) -> None:
        """Atomically publish a finished staging folder.

        TODO pseudocode (crash safety):
            d = staging_dir(song)
            assert all required files exist and are non-empty in d       # else raise IncompleteSong
            write d/song.json via tmp file + os.replace
            os.replace(d, root/song)       # atomic directory rename on the same NTFS volume
            index upsert (song row, artist names merged into artist table)
        A crash before os.replace leaves only staging (resumed later). A crash after it leaves a complete
        folder with a stale index, which open() repairs. Idempotent: if root/song already exists, drop d.
        """
        raise NotImplementedError
