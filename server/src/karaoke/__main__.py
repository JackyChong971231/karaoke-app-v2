"""Boot. The only module that knows every concrete class.

    uv run karaoke serve [--world real|fake] [--port 8080]
    uv run karaoke replay <journal.jsonl>

Boot order:
    config   = load %LOCALAPPDATA%/karaoke-v2/config.toml (library_dir, v1_dir for the importer)
    library  = Library(config.library_dir); library.open()
    world    = real: (YTMusicClient, RealStages(Downloader, Accelerator))
               fake: harness.fake_world(...)  -> fixture catalog + FakeStages + /test routes
    catalog  = Catalog(library, world.yt)
    store    = Store(appdata/party.json)
    state    = party.initial_state(store.load())           # restart offer derives from the snapshot
    loop     = PartyLoop(state, store, Journal(...), preparer, library, join_url=f"http://{lan_ip}:{port}/")
    preparer = Preparer(library, catalog, world.stages,
                        on_ready=lambda s: loop.submit(SongReady(s)),
                        on_board_change=loop.refresh)
    hub      = Hub(loop); loop.attach_hub(hub)
    importer = ImportService(V1Source(config.v1_dir), appdata/import-plan.json, catalog, library, preparer)
    run concurrently: uvicorn(routes(...)), loop.run(), preparer.run(), downloader.update_at_startup()
    open Edge in kiosk mode on the TV display: --kiosk --autoplay-policy=no-user-gesture-required http://localhost:port/tv
"""

from __future__ import annotations


def main() -> None:
    raise NotImplementedError


if __name__ == "__main__":
    main()
