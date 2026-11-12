# Karaoke server

The party server. It serves the TV page and the phone page from `web/dist`, holds the queue, and prepares songs.
Run every command from this folder. `uv` installs Python and the dependencies on first use.

## Run a party

```
uv run karaoke serve
```

The server prints the phone address, for example `http://192.168.1.20:8080/`, and opens the TV page in Edge in
kiosk mode. Put that address in front of the guests (the TV page shows it as a QR code).

| Option | Default | Meaning |
| --- | --- | --- |
| `--port N` | `8080` | HTTP and WebSocket port. |
| `--library DIR` | `%LOCALAPPDATA%\Karaoke\library` | Song folders. Must not be in a cloud-synced folder. |
| `--data DIR` | `%LOCALAPPDATA%\Karaoke` | `party.json`, journals, and the import plan. |
| `--v1 DIR` | none | A v1 install folder. Turns on the `/import` page. |
| `--no-open-tv` | | Do not launch Edge. Open `http://localhost:8080/tv` yourself. |

Build the web pages first with `npm install` and `npm run build` in `web/`. Without them the server still runs and
says the pages are missing.

## Run without internet or GPU

```
uv run karaoke serve --world fake
```

The fake world replaces only YouTube Music and the preparation stages. The reducer, the shell, the Preparer
scheduler, staging, install, HTTP, and WebSockets are the real code. It starts with three library songs and
generates small real media with ffmpeg, so the TV page plays a coloured video with a tone.

- Search `fake` finds online songs with an official video. `no video` finds a song without one, which opens the
  pick-a-video flow. A search containing `explode` fails, so the phone shows that online search is unavailable.
- Each preparation stage takes `--fake-delay` seconds (default 1).
- `GET /test/state` shows party state, the preparation board, and the journal path.
- `POST /test/prep/<song id>/hold`, `/advance`, `/release`, and `/fail?mode=once|always|crash` control one song's
  preparation.
- The fake world uses a new temporary data folder each run. Pass `--data DIR` twice to test restart keep-or-new.

## Test

```
uv run pytest
uv run lint-imports
uv run mypy src
```

`tests/test_server_e2e.py` starts the fake world and plays a party over WebSockets. Run it against a server you
started yourself to see the transcript:

```
uv run karaoke serve --world fake --no-open-tv
uv run python tests/test_server_e2e.py --url http://localhost:8080
```

## Other commands

- `uv run python -m karaoke.shell.export_schema --out ../web/src/wire/schema.json` writes the wire contract as
  JSON Schema. `npm run gen:wire` in `web/` runs it.
- `uv run karaoke replay <journal.jsonl>` replays a party journal through the reducer and prints each step.

## Where to change things

Party rules live in `src/karaoke/party/` as pure functions. `docs/design/architecture.md` explains the shape and
how to add a phone command.
