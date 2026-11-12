"""Persistence of DurableSnapshot. One JSON file, party.json, in the app data folder (not in the library,
not in OneDrive). The format is private to this module; nothing else reads the file."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from karaoke.party import DurableSnapshot
from karaoke.shell.codec import decode, encode

log = logging.getLogger(__name__)
_VERSION = 1


class Store:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> DurableSnapshot | None:
        """None if missing. A corrupt file is renamed to party.json.bad-<time> and treated as missing,
        so the party starts fresh rather than not at all."""
        if not self._path.exists():
            return None
        try:
            doc = json.loads(self._path.read_text(encoding="utf-8"))
            if doc.get("version") != _VERSION:
                raise ValueError(f"unknown version {doc.get('version')!r}")
            snap = decode(doc["snapshot"])
            if not isinstance(snap, DurableSnapshot):
                raise ValueError("not a snapshot")
            return snap
        except (ValueError, KeyError, TypeError) as e:
            bad = self._path.with_name(f"{self._path.name}.bad-{int(time.time())}")
            os.replace(self._path, bad)
            log.warning("party.json was unreadable (%s); moved to %s and starting fresh", e, bad)
            return None

    def save(self, snap: DurableSnapshot) -> None:
        """Write party.json.tmp, fsync, os.replace -> party.json. A crash leaves the old or the new file, never half."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(self._path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": _VERSION, "snapshot": encode(snap)}, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self._path)
