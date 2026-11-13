"""Favourite songs, one list per browser. Owns favourites.json in the app data folder, beside party.json.

Spec 00-product.md "Favourite songs" and 01-technical.md "Favourites":

- A list belongs to a browser (its stored `browserId`), not to the party, so nothing here touches party state.
- Each song is stored whole (video id, title, artist), so a favourite that is not in the library can be queued and
  prepared without searching again.
- When the laptop's address changes, a phone's browser starts empty and gets a new browserId. A restore offer finds
  the old list by the phone's Wi-Fi address, then by the typed name. The offer carries the list's name and song
  count only, never its songs or its browser id. Claiming it moves the list to the new browser.

Every change is written at once, crash-safe: a temporary file, fsync, then rename.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from karaoke.core import ArtistId, ArtistRef, SongId, SongMeta

log = logging.getLogger(__name__)
_VERSION = 1
MAX_SONGS = 500
NAME_MAX = 32
_OFFER_TTL_S = 15 * 60


@dataclass
class _List:
    name: str
    address: str | None
    songs: list[SongMeta]
    updated: float


@dataclass(frozen=True, slots=True)
class RestoreOffer:
    token: str
    name: str
    count: int


@dataclass
class Favourites:
    path: Path
    _lists: dict[str, _List] = field(default_factory=dict)
    _offers: dict[str, tuple[str, float]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def load(self) -> None:
        """Missing file: no lists. A corrupt file is moved aside as favourites.json.bad-<time>, never deleted."""
        if not self.path.exists():
            return
        try:
            doc = json.loads(self.path.read_text(encoding="utf-8"))
            if doc.get("version") != _VERSION:
                raise ValueError(f"unknown version {doc.get('version')!r}")
            self._lists = {bid: _decode_list(raw) for bid, raw in doc["lists"].items()}
        except (ValueError, KeyError, TypeError) as e:
            bad = self.path.with_name(f"{self.path.name}.bad-{int(time.time())}")
            os.replace(self.path, bad)
            log.warning("favourites.json was unreadable (%s); moved to %s", e, bad)
            self._lists = {}

    # ---- one browser's list -----------------------------------------------------------

    def songs(self, browser: str) -> tuple[SongMeta, ...]:
        found = self._lists.get(browser)
        return tuple(found.songs) if found else ()

    def get(self, browser: str, song: SongId) -> SongMeta | None:
        return next((s for s in self.songs(browser) if s.id == song), None)

    def add(self, browser: str, name: str, address: str | None, song: SongMeta) -> None:
        """Newest first. Adding a song already in the list moves it to the top."""
        with self._lock:
            lst = self._lists.get(browser) or _List(name, address, [], 0.0)
            lst.songs = [song, *(s for s in lst.songs if s.id != song.id)][:MAX_SONGS]
            self._touch(lst, name, address)
            self._lists[browser] = lst
            self._save()

    def remove(self, browser: str, song: SongId, name: str, address: str | None) -> None:
        with self._lock:
            lst = self._lists.get(browser)
            if lst is None or all(s.id != song for s in lst.songs):
                return
            lst.songs = [s for s in lst.songs if s.id != song]
            self._touch(lst, name, address)
            self._save()

    def seen(self, browser: str, name: str, address: str | None) -> None:
        """Remember the browser's latest name and address, so a restore offer can find its list later."""
        with self._lock:
            lst = self._lists.get(browser)
            if lst is None or (lst.name == name and lst.address == address):
                return
            self._touch(lst, name, address)
            self._save()

    # ---- restore after the laptop's address changed --------------------------------------

    def offer(self, address: str | None, name: str | None, exclude: str | None = None) -> RestoreOffer | None:
        """The most recently used non-empty list last seen from `address`, else the one whose name matches `name`
        (ignoring case and spaces). None when nothing matches."""
        candidates = [(bid, lst) for bid, lst in self._lists.items() if lst.songs and bid != exclude]
        by_address = [c for c in candidates if address and c[1].address == address]
        wanted = _name_key(name) if name else ""
        by_name = [c for c in candidates if wanted and _name_key(c[1].name) == wanted]
        pool = by_address or by_name
        if not pool:
            return None
        bid, lst = max(pool, key=lambda c: c[1].updated)
        token = secrets.token_urlsafe(12)
        now = time.monotonic()
        self._offers = {t: v for t, v in self._offers.items() if now - v[1] < _OFFER_TTL_S}
        self._offers[token] = (bid, now)
        return RestoreOffer(token, lst.name, len(lst.songs))

    def claim(self, token: str, browser: str, name: str, address: str | None) -> int | None:
        """Move the offered list to `browser`, merged in front of any songs it already has. Returns the song count,
        or None for an unknown or expired token."""
        with self._lock:
            found = self._offers.pop(token, None)
            if found is None or time.monotonic() - found[1] >= _OFFER_TTL_S:
                return None
            source = self._lists.pop(found[0], None)
            if source is None:
                return None
            mine = self._lists.get(browser)
            merged = [*(mine.songs if mine else []), *source.songs]
            unique = list({s.id: s for s in reversed(merged)}.values())[::-1][:MAX_SONGS]
            lst = _List(name, address, unique, 0.0)
            self._touch(lst, name, address)
            self._lists[browser] = lst
            self._save()
            return len(unique)

    # ---- disk ---------------------------------------------------------------------------

    def _touch(self, lst: _List, name: str, address: str | None) -> None:
        lst.name = name.strip()[:NAME_MAX] or lst.name
        lst.address = address or lst.address
        lst.updated = time.time()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        doc = {"version": _VERSION, "lists": {bid: _encode_list(lst) for bid, lst in self._lists.items()}}
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)


def _name_key(name: str) -> str:
    return "".join(name.split()).casefold()


def _encode_list(lst: _List) -> dict[str, Any]:
    return {"name": lst.name, "address": lst.address, "updated": lst.updated, "songs": [
        {"id": s.id, "title": s.title, "artistId": s.artist.id, "artist": s.artist.name, "durationS": s.duration_s}
        for s in lst.songs
    ]}


def _decode_list(raw: dict[str, Any]) -> _List:
    songs = [SongMeta(SongId(s["id"]), s["title"], ArtistRef(ArtistId(s["artistId"]), s["artist"]), float(s["durationS"]))
             for s in raw["songs"]]
    return _List(str(raw["name"]), raw.get("address"), songs, float(raw.get("updated", 0.0)))
