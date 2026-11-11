"""Persistence of DurableSnapshot. One JSON file in %LOCALAPPDATA%/karaoke-v2/party.json (not in the library,
not in OneDrive). Format is private to this module; nothing else reads the file."""

from __future__ import annotations

from pathlib import Path

from karaoke.party import DurableSnapshot


class Store:
    def __init__(self, path: Path) -> None:
        raise NotImplementedError

    def load(self) -> DurableSnapshot | None:
        """None if missing. A corrupt file is renamed to party.json.bad-<time> and treated as missing
        (the party starts fresh rather than not at all)."""
        raise NotImplementedError

    def save(self, snap: DurableSnapshot) -> None:
        """Write party.json.tmp, fsync, os.replace -> party.json. A crash leaves the old or the new file, never half."""
        raise NotImplementedError
