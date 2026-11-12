"""Boot. The only module that knows every concrete class.

    uv run karaoke serve [--world real|fake] [--port 8080] [--library DIR] [--data DIR] [--v1 DIR]
    uv run karaoke replay <journal.jsonl>

The real world keeps its state in %LOCALAPPDATA%\\Karaoke (party.json, journals, import plan) and the library
in %LOCALAPPDATA%\\Karaoke\\library, never in a cloud-synced folder. The fake world uses a fresh temporary
folder unless --data is given; pass the same --data to a second run to exercise restart keep-or-new.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import logging
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.routing import BaseRoute

from karaoke.core import SongId
from karaoke.party import SongReady, initial_state
from karaoke.shell.export_schema import protocol_hash
from karaoke.shell.http import Services, routes, static_mount
from karaoke.shell.hub import Hub
from karaoke.shell.journal import Journal, replay
from karaoke.shell.loop import PartyLoop
from karaoke.shell.store import Store
from karaoke.songs.catalog import Catalog, YouTubeMusic, YTMusicPort
from karaoke.songs.library import CloudSyncedRoot, Library
from karaoke.songs.prepare import Preparer, RealStages, Stages

log = logging.getLogger("karaoke")
WEB_DIST = Path(__file__).resolve().parents[3] / "web" / "dist"


def default_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Karaoke"


def lan_ip() -> str:
    """The address phones on the Wi-Fi reach. Connecting a UDP socket sends nothing; it only picks the route."""
    with contextlib.suppress(OSError), socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("192.168.0.1", 9))
        return str(s.getsockname()[0])
    return "127.0.0.1"


async def serve(args: argparse.Namespace) -> None:
    fake = args.world == "fake"
    data: Path = args.data or (Path(tempfile.mkdtemp(prefix="karaoke-fake-")) if fake else default_data_dir())
    library_dir: Path = args.library or data / "library"
    library = Library(library_dir)
    try:
        library.open()
    except CloudSyncedRoot as e:
        sys.exit(f"Refusing to use that library folder: {e}. Choose a local folder with --library.")

    harness_world = None
    yt: YouTubeMusic
    stages: Stages
    if fake:
        from karaoke.harness import fake_world
        harness_world = fake_world(data, library, args.fake_delay)
        yt, stages = harness_world.yt, harness_world.stages
    else:
        yt = YTMusicPort()
    catalog = Catalog(library, yt)
    if not fake:
        stages = RealStages(catalog)

    store = Store(data / "party.json")
    journal = Journal(data / "journal" / f"{time.strftime('%Y%m%d-%H%M%S')}.jsonl")
    join_url = f"http://{lan_ip()}:{args.port}/"

    loop_ref: list[PartyLoop] = []

    def on_ready(song: SongId) -> None:
        loop_ref[0].submit(SongReady(song))

    preparer = Preparer(library, catalog, stages, on_ready=on_ready, on_board_change=lambda: loop_ref[0].refresh())
    loop = PartyLoop(initial_state(store.load()), store, journal, preparer, library, join_url)
    loop_ref.append(loop)
    hub = Hub(loop, library, catalog, protocol_hash())
    loop.attach_hub(hub)

    importer = None
    if args.v1:
        from karaoke.importer import ImportService, V1Source
        importer = ImportService(V1Source(args.v1), data / "import-plan.json", catalog, library, preparer)

    services = Services(hub=hub, library=library, catalog=catalog, preparer=preparer, importer=importer,
                        web_dist=args.web_dist)
    extra: list[BaseRoute] = []
    if harness_world is not None:
        from karaoke.harness import harness_routes
        extra = harness_routes(harness_world, loop, preparer, journal)
    app = Starlette(routes=[*routes(services), *extra, static_mount(args.web_dist)])

    server = uvicorn.Server(uvicorn.Config(app, host=args.host, port=args.port, log_level="warning",
                                           ws_ping_interval=10, ws_ping_timeout=10))
    print(f"Karaoke ({args.world} world)")
    print(f"  Phones: {join_url}")
    print(f"  TV:     http://localhost:{args.port}/tv")
    print(f"  Data:   {data}")
    print(f"  Library: {library_dir}")
    if fake:
        print(f"  Test state: http://localhost:{args.port}/test/state")
    if not args.web_dist.joinpath("index.html").exists():
        print(f"  Note: web pages are not built yet ({args.web_dist}). Run `npm install && npm run build` in web/.")
    sys.stdout.flush()

    tasks = [asyncio.create_task(loop.run(), name="party-loop"),
             asyncio.create_task(preparer.run(), name="preparer")]
    if args.open_tv if args.open_tv is not None else not fake:
        asyncio.get_running_loop().call_later(1.0, open_tv, args.port, data)
    try:
        await server.serve()
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        journal.close()


def open_tv(port: int, data: Path) -> None:
    """Edge in kiosk mode with autoplay allowed, in its own profile so the flags apply even if Edge is open."""
    edge = shutil.which("msedge") or next(
        (p for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                     r"C:\Program Files\Microsoft\Edge\Application\msedge.exe") if Path(p).exists()), None)
    if edge is None:
        print(f"  Open http://localhost:{port}/tv on the TV screen (Edge was not found).")
        return
    subprocess.Popen([edge, "--kiosk", "--autoplay-policy=no-user-gesture-required", "--no-first-run",
                      f"--user-data-dir={data / 'edge-tv'}", f"http://localhost:{port}/tv"])


def main() -> None:
    parser = argparse.ArgumentParser(prog="karaoke")
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("serve", help="run the party server")
    s.add_argument("--world", choices=["real", "fake"], default="real")
    s.add_argument("--port", type=int, default=8080)
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--library", type=Path, help="song library folder (default: <data>/library)")
    s.add_argument("--data", type=Path, help=r"state folder (default: %%LOCALAPPDATA%%\Karaoke; fake: a new temp folder)")
    s.add_argument("--v1", type=Path, help="v1 install folder, enables the /import page")
    s.add_argument("--web-dist", type=Path, default=WEB_DIST)
    s.add_argument("--fake-delay", type=float, default=1.0, help="seconds per fake preparation stage")
    s.add_argument("--open-tv", dest="open_tv", action="store_true", default=None)
    s.add_argument("--no-open-tv", dest="open_tv", action="store_false")
    r = sub.add_parser("replay", help="re-run a journal through the reducer")
    r.add_argument("journal", type=Path)
    args = parser.parse_args()

    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.command == "replay":
        final = replay(args.journal, initial_state(None), verbose=True)
        print(f"final queue: {[e.song.title for e in final.queue]}  now: {final.now}")
        return
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(serve(args))


if __name__ == "__main__":
    main()
