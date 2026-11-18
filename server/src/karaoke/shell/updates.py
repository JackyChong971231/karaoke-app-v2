"""Upgrades for the installed app: one check of GitHub's latest release at start, and the download behind the
control page's Upgrade button.

Only the installed app (started by packaging/Karaoke.cmd with --installed) checks. The developer's copy is
updated with git. Installing is not done here: the app ends itself and its children through a job object (see
lifetime.py), so it downloads the installer, writes its path to `pending.txt`, and exits with UPGRADE_EXIT.
Karaoke.cmd, which is outside the job, runs the installer and starts the new version.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import urllib.request
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Literal

log = logging.getLogger(__name__)

REPO = "JackyChong971231/karaoke-app-v2"
LATEST_URL = os.environ.get("KARAOKE_UPDATE_URL") or f"https://api.github.com/repos/{REPO}/releases/latest"
"""KARAOKE_UPDATE_URL points the check at a stand-in release, to test an upgrade without publishing one."""
UPGRADE_EXIT = 75
"""The exit code that tells Karaoke.cmd an installer is waiting in pending.txt."""
_USER_AGENT = "karaoke-app-updater"
_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def running_version() -> str:
    try:
        return version("karaoke")
    except PackageNotFoundError:
        return "0.0.0"


def parse_version(text: str) -> tuple[int, int, int] | None:
    """`v2.10.0` or `2.10.0` -> (2, 10, 0). Anything else (pre-releases, junk) -> None."""
    m = _VERSION.match(text.strip())
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def is_newer(candidate: str, current: str) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    return a is not None and b is not None and a > b


@dataclass(frozen=True)
class Release:
    version: str
    notes_url: str
    installer_url: str
    installer_size: int


def pick_release(payload: object) -> Release | None:
    """The installer of a `releases/latest` answer, or None when it has none or the answer is not one."""
    if not isinstance(payload, dict):
        return None
    tag, notes = payload.get("tag_name"), payload.get("html_url")
    if not isinstance(tag, str) or not isinstance(notes, str) or parse_version(tag) is None:
        return None
    ver = tag.lstrip("v")
    for asset in payload.get("assets") or []:
        if isinstance(asset, dict) and asset.get("name") == f"Karaoke-Setup-{ver}.exe":
            url, size = asset.get("browser_download_url"), asset.get("size")
            if isinstance(url, str) and isinstance(size, int):
                return Release(ver, notes, url, size)
    return None


Phase = Literal["idle", "downloading", "failed"]


class Updates:
    def __init__(self, folder: Path, *, enabled: bool, failed_version: str | None = None) -> None:
        self._folder = folder
        self._enabled = enabled
        self.current = running_version()
        self.available: Release | None = None
        self.failed_version = failed_version
        self.phase: Phase = "idle"
        self.ready_to_install = asyncio.Event()

    async def check(self) -> None:
        """Once, at start. Any failure (offline, GitHub down, rate limit) is logged and the app says nothing."""
        if not self._enabled:
            return
        try:
            payload = await asyncio.to_thread(_get_json, LATEST_URL)
        except Exception as e:  # noqa: BLE001 - never let a check stop the party
            log.info("update check failed: %s", e)
            return
        release = pick_release(payload)
        if release is not None and is_newer(release.version, self.current):
            log.info("Karaoke %s is available (running %s)", release.version, self.current)
            self.available = release

    async def upgrade(self) -> bool:
        """Download the installer, write pending.txt, and signal the app to exit. False when nothing to do."""
        release = self.available
        if release is None or self.phase == "downloading":
            return False
        self.phase = "downloading"
        try:
            path = await asyncio.to_thread(self._download, release)
        except Exception as e:  # noqa: BLE001
            log.warning("upgrade download failed: %s", e)
            self.phase = "failed"
            return False
        (self._folder / "pending.txt").write_text(f"{path}\n{release.version}\n", encoding="utf-8")
        self.ready_to_install.set()
        return True

    def _download(self, release: Release) -> Path:
        self._folder.mkdir(parents=True, exist_ok=True)
        for old in self._folder.glob("Karaoke-Setup-*.exe"):
            old.unlink(missing_ok=True)
        dst = self._folder / f"Karaoke-Setup-{release.version}.exe"
        part = dst.with_suffix(".part")
        req = urllib.request.Request(release.installer_url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as res, part.open("wb") as out:
            while chunk := res.read(1 << 20):
                out.write(chunk)
        got = part.stat().st_size
        if got != release.installer_size:
            part.unlink(missing_ok=True)
            raise OSError(f"installer is {got} bytes, expected {release.installer_size}")
        part.replace(dst)
        return dst


def _get_json(url: str) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.loads(res.read().decode("utf-8"))
