"""The fake world for the verification harness (`karaoke serve --world fake`).

Fakes sit at the two places the app touches the internet or the GPU, and nowhere else, so the harness runs
the real reducer, real shell loop, real Preparer scheduler, real staging and install, real HTTP and WebSocket,
and the real built TV and phone pages:

    FakeYouTubeMusic   fixture search results (fixtures/catalog/*.json), incl. a song with NO official video
                       (drives the pick-a-video flow) and a query that raises (drives 'online search unavailable').
    FakeStages         copies fixture media (10 s tone stems, 10 s color-bar video, lyrics with known word times)
                       into staging. Each stage waits on a per-song gate the harness opens via /test, or a
                       configured delay, and can be told to fail, to fail once (update+retry path), or to crash
                       the 'process' mid-stage (resume-from-marker path).

Test-only routes (mounted only here; the real server has no /test prefix at all):
    GET  /test/state                  PartyState as JSON (dataclasses.asdict) + Preparer.board() + journal path
    POST /test/prep/{song}/advance    open the gate for the next stage
    POST /test/prep/{song}/fail       ?mode=once|always|crash
    POST /test/restart                persist, tear down, and boot again in-process (restart keep-or-new tests)
    POST /test/input                  submit a raw party Input (JSON), for states hard to reach through the UI

Browser-side probes (present in every build, read-only, cheap):
    window.__karaokeTv.probe()  -> { playId, audible, display, videoTime, slots: [{line, text, fills: number[]}],
                                     paused, semitones, vocalGain, loadedSongId }
    window.__karaokePhone.probe() -> { rev, pickFlow, pendingRequests }

Harness shape (the /pstack:create-verification-skill output will wrap it):
    Playwright + Microsoft Edge (channel 'msedge', proven on this laptop), autoplay flag on.
    One TV page + N phone contexts (each a fresh localStorage = a fresh singer).
    Assertions read probes and /test/state; actions use the real phone UI via data-testid selectors.

Scenarios the harness ships with (one per product rule that crosses the wire):
    fairness-example-1/2  queue A B B B B A C via three phones, assert queue order on a 4th phone
    unready-skip          queue X (gate closed) then Y (ready): Y plays, X stays at front, opens gate, X next
    filler                empty queue -> filler plays; queue a song mid-filler -> filler continues; skip -> song starts
    double-skip           two phones tap skip on the same playId -> exactly one song skipped
    restart-keep/new      queue 3, /test/restart, prompt on TV + 2 phones, first answer wins, second gets already_resolved
    pick-video            search a song with no official video -> candidate grid -> tap -> queued
    lyrics-clock          known fixture word times: at audible t the slot fills match; after pause/resume no backstep
    tv-reload             reload TV mid-song -> resumes at the reported position (+-0.5 s), same playId
    download-retry        fail=once -> one 'update' call, then ready; fail=always -> 'Can't download' on phones
    crash-resume          crash during 'separating' -> retry resumes at separate (download not repeated)
"""

from __future__ import annotations


def fake_world(fixtures_dir) -> object:
    raise NotImplementedError
