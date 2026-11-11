"""HTTP routes (Starlette). Queries and files only; nothing here changes party state.

    GET  /                          -> phone page        GET /tv -> TV page        GET /import -> import review page
    WS   /ws                        -> Hub.serve
    GET  /api/search?q=             -> contract.SearchResponse          (Catalog.search)
    GET  /api/artist/{artist_id}    -> contract.ArtistResponse          (Catalog.artist)
    GET  /api/video-choice?key=     -> contract.VideoChoiceResponse     (Catalog.resolve_video)
    GET  /media/{song_id}/{file}    -> Library.media_path; file restricted to vocab.MediaFile; Range requests on
    GET  /api/import                -> contract.ImportPlanView          (ImportService)
    POST /api/import/plan?limit=20  -> build or extend the plan (matching runs in the background)
    POST /api/import/decide         -> contract.ImportDecideRequest
    POST /api/import/run            -> start importing confirmed items
    /test/*                         -> mounted ONLY by harness.fake_world (see harness/__init__.py)

Every response body is a contract model serialized with by_alias=True. Route handlers are one call each.
"""

from __future__ import annotations


def routes(app_services) -> list:
    raise NotImplementedError
