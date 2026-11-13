"""HTTP routes (Starlette). Queries and files only; nothing here changes party state.

    GET  /                          -> phone page        GET /tv -> TV page        GET /import -> import review page
    WS   /ws                        -> Hub.serve
    GET  /api/search?q=             -> contract.SearchResponse          (Catalog.search)
    GET  /api/artist/{artist_id}    -> contract.ArtistResponse          (Catalog.artist, plus the singer's place)
    GET  /api/browse                -> contract.BrowseResponse          (the place boxes)
    GET  /api/place/{place_id}      -> contract.PlaceResponse           (Browse.page: 熱門 shelves, library, singers)
    GET  /api/ready                 -> contract.ReadyResponse           (every library song, newest first)
    POST /api/artist-place          -> contract.ArtistPlaceRequest      (control page: where a singer is from)
    GET  /api/video-choice?key=     -> contract.VideoChoiceResponse     (Catalog.resolve_video; import page)
    GET  /api/video-options?key=    -> contract.ChooseVideoResponse     (Catalog.video_options; phones; key may be lib:<id>)
    GET  /api/favourites?browser=   -> contract.FavouritesResponse      (Favourites; one list per browser)
    POST /api/favourites/add|remove -> contract.FavouritesResponse
    GET  /api/favourites/offer?name=&browser= -> contract.RestoreOfferResponse (by phone address, then name)
    POST /api/favourites/claim      -> contract.FavouritesResponse      (moves an offered list to this browser)
    GET  /media/{song_id}/{file}    -> Library.media_path; file restricted to vocab.MediaFile; Range requests on
    GET  /api/import                -> contract.ImportPlanView          (ImportService)
    POST /api/import/plan?limit=20  -> build or extend the plan (matching runs in the background)
    POST /api/import/decide         -> contract.ImportDecideRequest
    POST /api/import/run            -> start importing confirmed items
    /test/*                         -> mounted ONLY by harness.fake_world (see harness/__init__.py)

Every response body is a contract model serialized with by_alias=True.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import get_args

from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import FileResponse, PlainTextResponse, Response
from starlette.routing import BaseRoute, Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles

from karaoke import contract as c
from karaoke.core import ArtistId, ArtistRef, SongId, SongMeta
from karaoke.importer import ImportService, PlanItem
from karaoke.shell.hub import Hub
from karaoke.shell.views import board_readiness, song_view
from karaoke.songs.browse import PLACE_BY_ID, PLACES, Browse
from karaoke.songs.catalog import (
    Catalog, ChooseVideo, LibraryHit, OfficialVideo, OnlineKey, OnlineSong, OnlineUnavailable, PickId,
    UnknownOnlineKey, VideoResolution,
)
from karaoke.songs.library import Library
from karaoke.songs.prepare import Preparer, PrepStatus
from karaoke.vocab import MediaFile

log = logging.getLogger(__name__)
IMPORT_FIRST_BATCH = 20
_MEDIA_FILES: frozenset[str] = frozenset(get_args(MediaFile))
_MEDIA_TYPES = {".mp4": "video/mp4", ".opus": "audio/ogg", ".json": "application/json"}
_PAGES = {"/": "index.html", "/control": "control.html", "/tv": "tv.html", "/import": "import.html"}


@dataclass
class Services:
    hub: Hub
    library: Library
    catalog: Catalog
    preparer: Preparer
    importer: ImportService | None
    web_dist: Path
    browse: Browse | None = None
    background: set[asyncio.Task[None]] = field(default_factory=set)


def routes(s: Services) -> list[BaseRoute]:
    lib = s.library

    async def search(request: Request) -> Response:
        result = await s.catalog.search(request.query_params.get("q", "").strip())
        return _json(c.SearchResponse(library=_lib_hits(result.library), online=_online(result.online)))

    async def artist(request: Request) -> Response:
        page = await s.catalog.artist(ArtistId(request.path_params["artist_id"]))
        places = s.browse.places if s.browse else None
        return _json(c.ArtistResponse(
            artist=page.artist.name, artist_id=page.artist.id, library=_lib_hits(page.library),
            online=_online(page.online),
            place_id=places.place_of(page.artist.id) if places else None,
            place_chosen=places.chosen(page.artist.id) if places else False,
        ))

    # ---- browse by place ----

    async def browse(request: Request) -> Response:
        return _json(c.BrowseResponse(
            places=[c.PlaceSummary(place_id=p.id, label=p.label) for p in PLACES], ready_count=lib.count()))

    async def place(request: Request) -> Response:
        place_id = request.path_params["place_id"]
        if s.browse is None or place_id not in PLACE_BY_ID:
            return PlainTextResponse("unknown place", status_code=404)
        page = await s.browse.page(place_id)
        return _json(c.PlaceResponse(
            place_id=page.place.id, label=page.place.label,
            shelves=[c.ShelfView(title=sh.title, items=[_shelf_item(i) for i in sh.items]) for sh in page.shelves],
            library=_lib_hits(page.library),
            singers=[c.SingerView(artist_id=x.artist.id, name=x.artist.name, photo_url=x.photo_url) for x in page.singers],
            online_ok=page.online_ok,
        ))

    async def ready(request: Request) -> Response:
        hits = tuple(LibraryHit(r.meta, r.lyrics_source == "transcribed") for r in lib.newest())
        return _json(c.ReadyResponse(songs=_lib_hits(hits)))

    async def artist_place(request: Request) -> Response:
        try:
            req = c.ArtistPlaceRequest.model_validate_json(await request.body())
        except ValidationError as e:
            return PlainTextResponse(str(e), status_code=422)
        if s.browse is None:
            return PlainTextResponse("browse is off", status_code=404)
        s.browse.places.choose(ArtistRef(ArtistId(req.artist_id), req.name), req.place_id)
        return Response(status_code=204)

    async def video_choice(request: Request) -> Response:
        key = request.query_params.get("key")
        if not key:
            return PlainTextResponse("missing key", status_code=400)
        return _json(_resolution(await s.catalog.resolve_video(OnlineKey(key))))

    async def video_options(request: Request) -> Response:
        key = request.query_params.get("key")
        if not key:
            return PlainTextResponse("missing key", status_code=400)
        try:
            found = await s.catalog.video_options(OnlineKey(key))
        except UnknownOnlineKey:
            return PlainTextResponse("unknown key", status_code=404)
        return _json(_resolution(ChooseVideo(found)))

    # ---- favourites: one list per browser, saved on the laptop ----

    def favourites_view(browser: str) -> Response:
        songs = s.hub.favourites.songs(browser) if s.hub.favourites else ()
        return _json(c.FavouritesResponse(songs=[c.FavouriteView(song=song_view(m), ready=lib.has(m.id)) for m in songs]))

    async def favourites(request: Request) -> Response:
        return favourites_view(request.query_params.get("browser", ""))

    async def favourite_add(request: Request) -> Response:
        fav = s.hub.favourites
        try:
            req = c.FavouriteAddRequest.model_validate_json(await request.body())
        except ValidationError as e:
            return PlainTextResponse(str(e), status_code=422)
        if fav is None:
            return PlainTextResponse("favourites are off", status_code=404)
        meta = await _favourite_song(req.ref)
        if meta is None:
            return PlainTextResponse("unknown song", status_code=404)
        fav.add(req.browser_id, req.name, s.hub.device_of(request), meta)
        return favourites_view(req.browser_id)

    async def _favourite_song(ref: c.LibrarySongRef | c.OnlineSongRef) -> SongMeta | None:
        match ref:
            case c.LibrarySongRef(song_id=song_id):
                rec = lib.get(SongId(song_id))
                return rec.meta if rec else s.hub.known_song(SongId(song_id))
            case c.OnlineSongRef(online_key=key):
                try:
                    options = await s.catalog.video_options(OnlineKey(key))
                except UnknownOnlineKey:
                    return None
                return s.catalog.pick(options[0].pick) if options else None

    async def favourite_remove(request: Request) -> Response:
        try:
            req = c.FavouriteRemoveRequest.model_validate_json(await request.body())
        except ValidationError as e:
            return PlainTextResponse(str(e), status_code=422)
        if s.hub.favourites:
            s.hub.favourites.remove(req.browser_id, SongId(req.song_id), req.name, s.hub.device_of(request))
        return favourites_view(req.browser_id)

    async def restore_offer(request: Request) -> Response:
        """A phone whose browser starts empty (the laptop's address changed) asks for its old list: first by its
        Wi-Fi address, then by the typed name. Never returns the songs, only the list's name and size."""
        fav = s.hub.favourites
        name = request.query_params.get("name") or None
        found = fav.offer(s.hub.device_of(request), name, request.query_params.get("browser")) if fav else None
        if found is None:
            return _json(c.NoRestoreOffer(kind="none"))
        return _json(c.RestoreOfferFound(kind="offer", token=found.token, name=found.name, count=found.count))

    async def restore_claim(request: Request) -> Response:
        try:
            req = c.RestoreClaimRequest.model_validate_json(await request.body())
        except ValidationError as e:
            return PlainTextResponse(str(e), status_code=422)
        fav = s.hub.favourites
        if fav is None or fav.claim(req.token, req.browser_id, req.name, s.hub.device_of(request)) is None:
            return PlainTextResponse("offer expired", status_code=410)
        return favourites_view(req.browser_id)

    async def media(request: Request) -> Response:
        file = request.path_params["file"]
        if file not in _MEDIA_FILES:
            return PlainTextResponse("not found", status_code=404)
        path = lib.media_path(SongId(request.path_params["song_id"]), file)
        if path is None:
            return PlainTextResponse("not found", status_code=404)
        return FileResponse(path, media_type=_MEDIA_TYPES.get(path.suffix, "application/octet-stream"),
                            headers={"Cache-Control": "public, max-age=31536000, immutable"})

    def importer_route(handler: Callable[[ImportService, Request], Awaitable[Response]]) -> Callable[[Request], Awaitable[Response]]:
        async def endpoint(request: Request) -> Response:
            if s.importer is None:
                return PlainTextResponse("Importer not configured. Start with --v1 <v1 folder>.", status_code=404)
            return await handler(s.importer, request)
        return endpoint

    async def import_view(imp: ImportService, request: Request) -> Response:
        board = s.preparer.board()
        items = [_import_item(item, lib.has, board) for item in imp.items()]
        return _json(c.ImportPlanView(batch_limit=IMPORT_FIRST_BATCH, items=items))

    async def import_plan(imp: ImportService, request: Request) -> Response:
        raw = request.query_params.get("limit")
        limit = int(raw) if raw and raw.isdigit() else None
        task = asyncio.create_task(imp.plan(limit))
        s.background.add(task)
        task.add_done_callback(_finish_background(s.background))
        return PlainTextResponse("matching", status_code=202)

    async def import_decide(imp: ImportService, request: Request) -> Response:
        try:
            req = c.ImportDecideRequest.model_validate_json(await request.body())
        except ValidationError as e:
            return PlainTextResponse(str(e), status_code=422)
        imp.decide(req.item_id, req.decision, PickId(req.pick_id) if req.pick_id else None)
        return await import_view(imp, request)

    async def import_run(imp: ImportService, request: Request) -> Response:
        imp.run()
        return await import_view(imp, request)

    def page(name: str) -> Callable[[Request], Awaitable[Response]]:
        async def endpoint(request: Request) -> Response:
            path = s.web_dist / name
            if not path.exists():
                return PlainTextResponse(
                    f"The web pages are not built ({path} is missing). Run `npm install && npm run build` in web/.",
                    status_code=503,
                )
            return FileResponse(path, media_type="text/html", headers={"Cache-Control": "no-cache"})
        return endpoint

    return [
        *(Route(url, page(name)) for url, name in _PAGES.items()),
        WebSocketRoute("/ws", s.hub.serve),
        Route("/api/search", search),
        Route("/api/artist/{artist_id}", artist),
        Route("/api/browse", browse),
        Route("/api/place/{place_id}", place),
        Route("/api/ready", ready),
        Route("/api/artist-place", artist_place, methods=["POST"]),
        Route("/api/video-choice", video_choice),
        Route("/api/video-options", video_options),
        Route("/api/favourites", favourites),
        Route("/api/favourites/add", favourite_add, methods=["POST"]),
        Route("/api/favourites/remove", favourite_remove, methods=["POST"]),
        Route("/api/favourites/offer", restore_offer),
        Route("/api/favourites/claim", restore_claim, methods=["POST"]),
        Route("/media/{song_id}/{file}", media),
        Route("/api/import", importer_route(import_view)),
        Route("/api/import/plan", importer_route(import_plan), methods=["POST"]),
        Route("/api/import/decide", importer_route(import_decide), methods=["POST"]),
        Route("/api/import/run", importer_route(import_run), methods=["POST"]),
    ]


def static_mount(web_dist: Path) -> Mount:
    """Built assets (hashed JS and CSS). Mounted last so it never shadows an API route."""
    return Mount("/", app=StaticFiles(directory=web_dist, check_dir=False), name="web")


def _json(model: c.Wire) -> Response:
    return Response(model.model_dump_json(by_alias=True), media_type="application/json")


def _lib_hits(hits: tuple[LibraryHit, ...]) -> list[c.LibrarySongHit]:
    return [c.LibrarySongHit(song=song_view(h.song), lyrics_flagged=h.lyrics_flagged) for h in hits]


def _online(online: tuple[OnlineSong, ...] | OnlineUnavailable) -> c.OnlineOk | c.OnlineDown:
    if isinstance(online, OnlineUnavailable):
        return c.OnlineDown(kind="unavailable")
    return c.OnlineOk(kind="ok", songs=[
        c.OnlineSongHit(online_key=o.key, title=o.title, artist=o.artist.name, artist_id=o.artist.id,
                        duration_s=o.duration_s, thumbnail_url=o.thumbnail_url)
        for o in online
    ])


def _shelf_item(item: LibraryHit | OnlineSong) -> c.LibraryShelfItem | c.OnlineShelfItem:
    if isinstance(item, LibraryHit):
        return c.LibraryShelfItem(kind="library", hit=_lib_hits((item,))[0])
    online = _online((item,))
    assert isinstance(online, c.OnlineOk)
    return c.OnlineShelfItem(kind="online", song=online.songs[0])


def _resolution(r: VideoResolution) -> c.OfficialFound | c.ChooseVideoResponse:
    match r:
        case OfficialVideo(pick=pick):
            return c.OfficialFound(kind="official", pick_id=pick)
        case ChooseVideo(candidates=candidates):
            return c.ChooseVideoResponse(kind="choose", candidates=[
                c.VideoCandidateView(pick_id=v.pick, title=v.title, channel=v.channel,
                                     thumbnail_url=v.thumbnail_url, duration_s=v.duration_s, official=v.official)
                for v in candidates
            ])


def _import_item(item: PlanItem, has: Callable[[SongId], bool], board: Mapping[SongId, PrepStatus]) -> c.ImportItemView:
    final = item.final
    shown = final or item.proposed
    return c.ImportItemView(
        item_id=item.v1.folder.name,
        v1_title=item.v1.raw_title,
        v1_play_count=item.v1.play_count,
        proposed=song_view(shown) if shown else None,
        video=None,
        reuse_v1_video=item.reuse_v1_video,
        decision=item.decision,
        imported=final is not None and has(final.id),
        readiness=board_readiness(final.id, board) if final and final.id in board else None,
    )


def _finish_background(tasks: set[asyncio.Task[None]]) -> Callable[[asyncio.Task[None]], None]:
    def done(task: asyncio.Task[None]) -> None:
        tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            log.error("background import task failed", exc_info=task.exception())
    return done
