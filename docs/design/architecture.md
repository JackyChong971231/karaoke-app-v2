# Architecture

This is the design the code follows. It was produced by `/pstack:architect` from two independent candidates and merged on 2026-11-11. The specs in `docs/spec/` say what the app does. This file says how the code is shaped.

## Problem

One Windows laptop runs a party. The server prepares songs (download, vocal separation, word-timed lyrics). A TV browser page plays them. Many phones edit the queue at the same time. The audio clock lives in the TV browser, which can reload. Preparation is slow (25 s on GPU, minutes on CPU) and must survive crashes. v1 failed because UI, playback, downloads, and processing shared state and called into each other.

## Usage

To change a party rule, edit `server/src/karaoke/party/`. Rules are pure functions:

```python
step = reduce(state, input)        # the only writer of party state
state = step.state                 # step.outcome is the reply to the sender
```

You never write code to save, broadcast, or start preparation. After every step the shell derives all of them from the new state:

```python
durable(state)              -> Store.save          (when changed)
preparation_demand(state)   -> Preparer.set_demand (when changed)
filler_request(state)       -> Library.random_pick -> FillerPicked input
views(state, board, clock)  -> Hub.publish         (full snapshots to TV and phones)
```

To add a phone action:

1. Add a command model to `contract.py`.
2. Add an input type to `party/inputs.py`.
3. Add its branch to `reduce`.
4. Add its line to `shell/parse.py`.
5. Call it from the phone with `store.run(...)`.

Steps 3 and 4 are forced: `assert_never` fails type checking until both handle the new type. TypeScript fails to compile until the page handles the regenerated union.

## Shape

### Data flow

```
phones --cmd--> Hub --parse--> PartyLoop inbox --> reduce (pure) --> state
TV --report----^                    ^                                  |
Preparer --SongReady----------------+                                  |
filler pick --FillerPicked----------+                                  v
              reconcile after every step: durable, preparation_demand, filler_request, views
TV --clock (4 Hz telemetry)--> Hub --> phones        (never reduced)
```

### Owners

| State | Owner | Durable form |
| --- | --- | --- |
| Queue, fairness, now playing, restart prompt, settings | `party` reducer | `party.json`, written from `durable(state)`. It has no fairness field, so a restart cannot keep counts. |
| Preparation jobs and progress | `songs.prepare.Preparer` | The staging folder. A step is done when its output file exists. |
| Song folders and search index | `songs.library.Library` | `<root>/<video id>/`. `index.sqlite` is derived and rebuilt from the folders. |
| Search results and video candidates | `songs.catalog.Catalog` | Memory only. Phones send back a candidate ID, never metadata. |
| Import plan | `importer` | `import-plan.json`. "Imported" is derived from the library. |
| Actual audio clock | TV page | None. The TV reports it. |

### Rules

- **Identity.** `PlayId` increases each time a song starts. Pause, skip, key, and track-ended carry it. A stale `PlayId` is rejected, so a double skip advances one song. Setters are absolute, never toggles.
- **Singer.** A singer is a phone: `net:<Wi-Fi address>`, read by the hub from the connection. Any browser on the laptop is `net:laptop`. The browser's stored ID (`browserId`) keys favourites only. Each queue entry keeps the name it was queued with. The fake world reads a `karaoke-test-device` cookie instead of the address, because every test phone runs on one computer.
- **Fairness.** `round = sung tonight + queued + 1`, fixed when the entry is added. A song counts as sung when it starts. A new entry goes right after the last entry with a smaller `(round, join index)`. Manual moves are never undone.
- **Turn order.** Start the first ready entry in queue order. If none is ready, play a filler.
- **Filler.** A random library song not played in the last 20 fillers. When every library song is among them, the one played longest ago, so a small library rotates. A TV that fails to load a song waits 3 s before reporting it. It is `Playing(origin=Filler())`, not a queue entry. A newly ready queue song does not interrupt it.
- **Restart.** A non-empty saved queue opens a keep-or-new prompt. The first answer wins. Keep renumbers rounds and join order from the kept order. Queue edits wait for the answer.
- **TV.** The TV converges to the `TvView` it receives. It loads only when `PlayId` changes. After a reload it resumes at the last reported position for that `PlayId`. The audible clock is `inputTime - (stretch latency + baseLatency + outputLatency)` and holds the seek target until a fresh update arrives.
- **Preparation.** Steps run fetch, separate, lyrics, install. Each output is written as `.part` and renamed. Install moves the staging folder into the library with one rename. Two downloads run at once. One accelerator child process runs Demucs and Whisper, on CUDA when present, else CPU at below-normal priority. Party demand comes before import demand.
- **Wire contract.** `contract.py` (pydantic) is the only definition. The build generates `web/src/wire/generated.ts` from it. The file is gitignored, so it cannot go stale. A protocol hash in the hello message makes an outdated page reload.

### Module map

```
server/src/karaoke/
  core.py vocab.py contract.py      shared IDs, closed vocabularies, wire contract
  party/                            pure: model, inputs, reduce, fairness, projections
  songs/library.py                  folders + derived index
  songs/catalog.py                  YouTube Music search, official-video rule, candidates
  songs/prepare/                    Preparer, staged pipeline, yt-dlp, accelerator child, lyrics
  importer/                         v1 reader (read-only), plan, review, run
  shell/                            loop, parse, views, hub, http, store, journal, export_schema
  harness/                          fake world for end-to-end tests
web/src/
  wire/                             generated contract, socket
  tv/                               audio engine and clock, lyrics, reconcile, page
  phone/                            store, pick-a-video flow, labels, screens
  control/                          laptop control page: the phone screens side by side (App desk)
  import/                           import review page
```

## Synthesis decision

Two candidates were built in parallel, both on Claude. No cross-family judge was available, so the base was picked by reading both against a rubric: one owner per state, crash safety, interface depth, playback clock ownership, and how hard each design makes it for a future change to break an invariant.

- **Base: candidate 1**, one pure reducer whose effects are projections of state. A new rule cannot forget to save, broadcast, or prepare. Restart recovery is the first reconcile. Every party rule is testable without a server.
- **Grafted from candidate 2.** A preparation step counts as done when its output file exists, with no extra marker files. The protocol hash in hello reloads stale pages. Imported songs without an official video reuse their v1 files, so only lyrics are redone.
- **Rejected from candidate 2.** Owner objects that save themselves: they put I/O inside the party rules and need a test to keep mutations synchronous.
- **Convergence.** Both candidates chose the same answers on their own for these: one owner per state, ID-tagged commands, the TV converging to a declarative view, file-based crash-safe preparation, demand lists per source, and pydantic-to-TypeScript generation.

## Decisions on open questions

The user asked for an unattended build, so these were decided and reported, not asked:

- A singer joins tonight at their first queued song.
- Insertion follows the spec rule even after manual moves.
- Keep renumbers rounds and join order from the kept order.
- Vocal level persists across songs. Key resets to 0 for each new song.
- Queue edits wait while the restart prompt is open.
- A queue with no ready songs plays a filler.
- `karaoke serve` opens the TV page in Edge with the autoplay flag, in kiosk mode on the second screen, and the control page maximized on the main screen (`shell/screens.py`). With one screen both open as plain windows. A page opened by hand shows a one-time **Start** button.
- v1 songs with a `meta.json` URL use that video ID. Others are found by search and confirmed on the review page.

## Tradeoffs accepted

- We accept recomputing four projections after every input, in exchange for persistence, broadcast, and preparation that no branch can forget.
- We accept full snapshots of about 10 KB per change, in exchange for no patch logic and reconnect being the same as update.
- We accept no optimistic edits on phones, in exchange for never reconciling a guess with another phone's edit.
- We accept that a removed song keeps preparing, in exchange for no cancel path. The finished song lands in the library.

## Alternatives considered

- **Effects returned by the reducer.** Every branch would have to remember its effects, and an effect emitted just before a crash is lost.
- **Owner objects that persist themselves.** Simple call sites, but I/O inside party rules and a wide surface of about 18 methods.
- **Event sourcing.** Restart discards fairness anyway, so replay would special-case what it reconstructs.
- **Pipeline modules per stage**, as in the first spec draft. That splits one job's retries and staging across three modules.
