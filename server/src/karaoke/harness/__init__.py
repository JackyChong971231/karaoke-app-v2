"""The fake world for the verification harness (`karaoke serve --world fake`).

Fakes sit at the two places the app touches the internet or the GPU, and nowhere else, so the harness runs
the real reducer, real shell loop, real Preparer scheduler, real staging and install, real HTTP and WebSocket,
and the real built TV and phone pages:

    FakeYouTubeMusic   fixture search results (fakes.CATALOG), incl. a song with NO official video
                       ("No Video Song", drives the pick-a-video flow) and a query that raises
                       (any query containing "explode", drives 'online search unavailable').
    FakeStages         copies real ffmpeg-generated fixture media (10 s tone stems, 10 s solid-colour video,
                       lyrics with known word times) into staging. Each stage takes --fake-delay seconds, or
                       waits for /test/prep/<song>/advance when the song is held, and can be told to fail.
    seed_library       three library songs at boot, so library search, ready-at-once queueing, and filler work.

Test-only routes (mounted only here; the real server has no /test prefix at all):
    GET  /test/state                  party state, preparation board, fake stage calls, journal path (JSON)
    POST /test/prep/{song}/hold       stages of this song wait for /advance
    POST /test/prep/{song}/advance    let the held song's current stage finish
    POST /test/prep/{song}/release    stop holding; remaining stages run with the normal delay
    POST /test/prep/{song}/fail       ?mode=once|always|crash
    POST /test/input                  submit a raw party Input (codec JSON), for states hard to reach through the UI
    GET  /test/thumb/{video}.svg      solid-colour thumbnail, so the video grid renders offline

Restart scenarios restart the process itself with the same --data folder: that is the real boot path.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path
from typing import get_args

from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import BaseRoute, Route

from karaoke.core import SongId
from karaoke.harness.fakes import FailMode, FakeStages, FakeYouTubeMusic, seed_library
from karaoke.harness.media import COLOURS, ensure_media
from karaoke.party import Input
from karaoke.shell.codec import decode, encode
from karaoke.shell.journal import Journal
from karaoke.shell.loop import PartyLoop
from karaoke.songs.library import Library
from karaoke.songs.prepare import Preparer


@dataclass(frozen=True, slots=True)
class FakeWorld:
    yt: FakeYouTubeMusic
    stages: FakeStages


def fake_world(data_dir: Path, library: Library, delay_s: float) -> FakeWorld:
    media = ensure_media(data_dir / "fixtures")
    seed_library(library, media)
    return FakeWorld(FakeYouTubeMusic(), FakeStages(media, delay_s))


def harness_routes(world: FakeWorld, loop: PartyLoop, preparer: Preparer, journal: Journal) -> list[BaseRoute]:
    stages = world.stages

    async def state(request: Request) -> Response:
        board = {song: dataclasses.asdict(status) for song, status in preparer.board().items()}
        views = loop.views()
        return JSONResponse({
            "party": encode(loop.state),
            "board": board,
            "stages": stages.describe(),
            "journal": str(journal.path),
            "views": [v.model_dump(by_alias=True) for v in views] if views else None,
        })

    async def prep(request: Request) -> Response:
        song = SongId(request.path_params["song"])
        match request.path_params["action"]:
            case "hold":
                stages.hold(song)
            case "advance":
                stages.advance(song)
            case "release":
                stages.release(song)
            case "fail":
                mode = request.query_params.get("mode", "always")
                if mode not in get_args(FailMode):
                    return PlainTextResponse(f"mode must be one of {get_args(FailMode)}", status_code=400)
                stages.fail(song, mode)  # type: ignore[arg-type]
            case other:
                return PlainTextResponse(f"unknown action {other}", status_code=404)
        return JSONResponse(stages.describe())

    async def submit_input(request: Request) -> Response:
        inp: Input = decode(json.loads(await request.body()))
        outcome = await loop.submit(inp)
        return JSONResponse(encode(outcome))

    async def thumbnail(request: Request) -> Response:
        video = request.path_params["video"]
        colour = COLOURS[sum(map(ord, video)) % len(COLOURS)].replace("0x", "#")
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180">'
               f'<rect width="320" height="180" fill="{colour}"/>'
               f'<text x="16" y="100" font-size="20" fill="#fff" font-family="sans-serif">{video}</text></svg>')
        return Response(svg, media_type="image/svg+xml")

    return [
        Route("/test/state", state),
        Route("/test/prep/{song}/{action}", prep, methods=["POST"]),
        Route("/test/input", submit_input, methods=["POST"]),
        Route("/test/thumb/{video}.svg", thumbnail),
    ]


__all__ = ["FakeWorld", "fake_world", "harness_routes"]
