"""A whole party over the real wire: `karaoke serve --world fake` in a subprocess, one TV and two phones as
WebSocket clients, songs found through the HTTP search and video-choice routes.

Also runnable against a server you started yourself, printing the transcript:

    uv run karaoke serve --world fake
    uv run python tests/test_server_e2e.py --url http://localhost:8080
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed


class Client:
    def __init__(self, ws: ClientConnection, name: str) -> None:
        self.ws, self.name = ws, name
        self.view: dict[str, Any] | None = None
        self.protocol: str | None = None
        self.clock: dict[str, Any] | None = None
        self.superseded = False
        self._replies: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._next = 0
        self._changed = asyncio.Event()
        self._reader = asyncio.create_task(self._read())

    @classmethod
    async def open(cls, url: str, name: str, hello: dict[str, Any], device: str | None = None) -> Client:
        """Every client runs on this computer, so the fake world's test cookie gives each phone its own address.
        `device` defaults to the client's name: one name, one phone."""
        cookie = {"Cookie": f"karaoke-test-device={device or name}"}
        client = cls(await connect(url.replace("http", "ws", 1) + "/ws", additional_headers=cookie), name)
        await client.ws.send(json.dumps(hello))
        await client.until(lambda v: True)
        return client

    async def _read(self) -> None:
        with contextlib.suppress(ConnectionClosed):
            await self._read_until_closed()

    async def _read_until_closed(self) -> None:
        async for raw in self.ws:
            msg = json.loads(raw)
            match msg["kind"]:
                case "serverHello":
                    self.protocol = msg["protocol"]
                case "phoneView" | "tvView":
                    self.view = msg["view"]
                case "reply":
                    self._replies.pop(msg["requestId"]).set_result(msg["outcome"])
                case "clock":
                    self.clock = msg
                case "superseded":
                    self.superseded = True
            self._changed.set()

    async def send(self, command: dict[str, Any], envelope: str = "phoneCommand") -> dict[str, Any]:
        self._next += 1
        fut: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._replies[self._next] = fut
        await self.ws.send(json.dumps({"kind": envelope, "requestId": self._next, "command": command}))
        return await asyncio.wait_for(fut, 10)

    async def until(self, ok: Callable[[dict[str, Any]], bool], timeout: float = 20) -> dict[str, Any]:
        async def wait() -> dict[str, Any]:
            while self.view is None or not ok(self.view):
                self._changed.clear()
                await self._changed.wait()
            return self.view

        return await asyncio.wait_for(wait(), timeout)

    async def close(self) -> None:
        await self.ws.close()
        self._reader.cancel()


def get(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read())


async def aget(url: str) -> Any:
    """HTTP off the event loop, so the WebSocket clients keep answering keepalive pings."""
    return await asyncio.to_thread(get, url)


def letters(view: dict[str, Any]) -> str:
    return "".join(e["singerName"][0] for e in view["queue"])


async def party(url: str, log: Callable[[str], None]) -> None:
    tv = await Client.open(url, "tv", {"kind": "tvHello"})
    amy = await Client.open(url, "amy", {"kind": "phoneHello", "browserId": "browser-amy", "name": "Amy"})
    ben = await Client.open(url, "ben", {"kind": "phoneHello", "browserId": "browser-ben", "name": "Ben"})
    assert tv.protocol and tv.protocol == amy.protocol
    log(f"connected: 1 TV + 2 phones, protocol {tv.protocol}")

    v = await amy.until(lambda v: v["now"] is not None)
    filler = v["now"]
    assert filler["isFiller"] and filler["singerName"] is None
    log(f"empty queue -> filler plays: playId={filler['playId']} {filler['song']['title']!r}")

    async def pick(query: str, title: str) -> dict[str, Any]:
        found = await aget(f"{url}/api/search?q={query}")
        song = next(s for s in found["online"]["songs"] if s["title"] == title)
        choice = await aget(f"{url}/api/video-choice?key={song['onlineKey']}")
        assert choice["kind"] == "official"
        return {"kind": "queuePick", "pickId": choice["pickId"]}

    async def library(title: str) -> dict[str, Any]:
        hit = (await aget(f"{url}/api/search?q={urllib.request.quote(title)}"))["library"][0]
        return {"kind": "queueLibrary", "songId": hit["song"]["songId"]}

    plan = [
        (amy, await pick("fake", "Fake Song One")),
        (ben, await pick("fake", "Second Fake Hit")),
        (ben, await library("Morning Sun")),
        (ben, await pick("fake", "Complicated Fake")),
        (ben, await library("河流")),
        (amy, await library("Night Drive")),
    ]
    for phone, cmd in plan:
        outcome = await phone.send(cmd)
        assert outcome == {"kind": "accepted"}, outcome
    log("queued from phones in order: Amy, Ben, Ben, Ben, Ben, Amy")
    v = await ben.until(lambda v: len(v["queue"]) == 6)
    for e in v["queue"]:
        log(f"  {e['entryId']:>2} {e['singerName']:<4} {e['song']['title']:<18} {e['readiness']['kind']}")
    log(f"snapshot queue order: {letters(v)} (fairness rule expects ABABBB)")
    assert letters(v) == "ABABBB"
    assert v["now"]["isFiller"], "ready library songs do not interrupt the filler"

    skips = await asyncio.gather(amy.send({"kind": "skip", "playId": filler["playId"]}),
                                 ben.send({"kind": "skip", "playId": filler["playId"]}))
    log(f"two phones skip playId {filler['playId']} at once -> {[s.get('reason', s['kind']) for s in skips]}")
    assert sorted(s["kind"] for s in skips) == ["accepted", "rejected"]
    assert {"kind": "rejected", "reason": "stale_play"} in skips

    v = await amy.until(lambda v: v["now"]["playId"] != filler["playId"])
    now = v["now"]
    log(f"now playing: {now['song']['title']!r} by {now['singerName']} (first READY entry; unready ones keep the front)")
    log(f"queue after: {letters(v)}  readiness: {[e['readiness'].get('stage', 'ready') for e in v['queue']]}")
    assert now["song"]["title"] == "Night Drive" and now["singerName"] == "Amy" and letters(v) == "ABBBB"
    tv_view = await tv.until(lambda t: t["play"] and t["play"]["playId"] == now["playId"])
    assert tv_view["upNext"]["singerName"] == "Amy"

    await tv.ws.send(json.dumps({"kind": "clock", "playId": now["playId"], "positionS": 4.25, "paused": False}))
    await asyncio.wait_for(_until(lambda: amy.clock is not None and ben.clock is not None), 5)
    assert amy.clock is not None
    log(f"TV clock relayed to phones: positionS={amy.clock['positionS']}")

    v = await amy.until(lambda v: v["queue"][0]["readiness"]["kind"] == "ready", timeout=30)
    log(f"Amy's first song finished preparing: {v['queue'][0]['song']['title']!r} is ready at the front")
    ended = await tv.send({"kind": "trackEnded", "playId": now["playId"]}, envelope="tvCommand")
    assert ended == {"kind": "accepted"}
    v = await amy.until(lambda v: v["now"]["playId"] == now["playId"] + 1)
    log(f"TV reports track ended -> now playing {v['now']['song']['title']!r} by {v['now']['singerName']}")
    assert v["now"]["song"]["title"] == "Fake Song One" and v["now"]["singerName"] == "Amy"
    late = await tv.send({"kind": "trackEnded", "playId": now["playId"]}, envelope="tvCommand")
    assert late == {"kind": "rejected", "reason": "stale_play"}

    no_video = (await aget(f"{url}/api/search?q=no%20video"))["online"]["songs"][0]
    choose = await aget(f"{url}/api/video-choice?key={no_video['onlineKey']}")
    assert choose["kind"] == "choose" and len(choose["candidates"]) == 3
    log(f"song without an official video -> {len(choose['candidates'])} candidates to choose from")
    assert (await aget(f"{url}/api/search?q=explode"))["online"] == {"kind": "unavailable"}

    playing = v["now"]["song"]["songId"]
    req = urllib.request.Request(f"{url}/media/{playing}/video.mp4", headers={"Range": "bytes=0-99"})
    status, body = await asyncio.to_thread(_fetch, req)
    assert status == 206 and len(body) == 100
    log(f"TV media served with Range: /media/{playing}/video.mp4 -> 206, 100 bytes")

    eve = await Client.open(url, "eve", {"kind": "phoneHello", "browserId": "browser-eve", "name": "Eve"})
    await eve.ws.send(json.dumps({"kind": "tvCommand", "requestId": 1, "command": {"kind": "trackEnded", "playId": 1}}))
    await asyncio.wait_for(eve.ws.wait_closed(), 5)
    assert eve.ws.close_code == 1008
    log("a phone sending a TV command is disconnected with 1008")

    tv2 = await Client.open(url, "tv2", {"kind": "tvHello"})
    await asyncio.wait_for(_until(lambda: tv.superseded), 5)
    assert tv2.view is not None and tv2.view["play"]["playId"] == v["now"]["playId"]
    log("a second TV page supersedes the first and receives the current play")
    for c in (tv, tv2, amy, ben):
        await c.close()


def _fetch(req: urllib.request.Request) -> tuple[int, bytes]:
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, r.read()


async def _until(ok: Callable[[], bool]) -> None:
    while not ok():
        await asyncio.sleep(0.05)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@contextlib.contextmanager
def running_server(data: Path) -> Iterator[str]:
    """`karaoke serve --world fake` on a free port. Stopping it is a hard kill on Windows, like a crash."""
    port = _free_port()
    log_path = data / f"server-{port}.log"
    with open(log_path, "wb") as out:
        proc = subprocess.Popen(
            [sys.executable, "-m", "karaoke", "serve", "--world", "fake", "--port", str(port), "--host", "127.0.0.1",
             "--data", str(data), "--fake-delay", "1.5", "--no-open-tv"],
            stdout=out, stderr=subprocess.STDOUT,
        )
        url = f"http://127.0.0.1:{port}"
        try:
            deadline = time.monotonic() + 30
            while True:
                try:
                    get(f"{url}/test/state")
                    break
                except OSError:
                    if proc.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError(log_path.read_text(errors="replace"))
                    time.sleep(0.2)
            yield url
        finally:
            proc.terminate()
            proc.wait(10)


@pytest.fixture
def server(tmp_path: Path) -> Iterator[str]:
    with running_server(tmp_path) as url:
        yield url


def say(line: str) -> None:
    sys.stdout.flush()
    sys.stdout.buffer.write(line.encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()


def test_party_over_the_wire(server: str) -> None:
    asyncio.run(party(server, say))
    state = get(f"{server}/test/state")
    assert state["party"]["fairness"]["sung"] == {"net:amy": 2}


async def mic_hog(url: str) -> None:
    """Spec "One phone is one singer": a 咪霸 renames between songs and opens a second browser on the same phone,
    hoping to look like new singers. Fairness still counts one phone; each song shows the name it was queued with."""
    tv = await Client.open(url, "tv", {"kind": "tvHello"})
    hog = await Client.open(url, "hog", {"kind": "phoneHello", "browserId": "b1", "name": "Hog"}, device="phone-h")
    ben = await Client.open(url, "ben", {"kind": "phoneHello", "browserId": "b2", "name": "Ben"})
    hog_tab = await Client.open(url, "tab", {"kind": "phoneHello", "browserId": "b3", "name": "Not Hog"},
                                device="phone-h")
    await hog.until(lambda v: v["now"] is not None)
    assert await hog.send({"kind": "setPaused", "playId": hog.view["now"]["playId"], "paused": True}) \
        == {"kind": "accepted"}  # type: ignore[index]

    async def queue(phone: Client, title: str) -> None:
        hit = (await aget(f"{url}/api/search?q={urllib.request.quote(title)}"))["library"][0]
        assert await phone.send({"kind": "queueLibrary", "songId": hit["song"]["songId"]}) == {"kind": "accepted"}

    await queue(hog, "Morning Sun")
    assert await hog.send({"kind": "rename", "name": "Fresh Name"}) == {"kind": "accepted"}
    await queue(hog, "河流")
    await queue(hog_tab, "Night Drive")
    await queue(ben, "Morning Sun")
    v = await ben.until(lambda v: len(v["queue"]) == 4)
    names = [e["singerName"] for e in v["queue"]]
    assert names == ["Hog", "Ben", "Fresh Name", "Not Hog"], names
    assert len({e["singerId"] for e in v["queue"] if e["singerName"] != "Ben"}) == 1
    for c in (tv, hog, ben, hog_tab):
        await c.close()


def test_renaming_or_a_second_browser_on_one_phone_is_still_one_singer(server: str) -> None:
    asyncio.run(mic_hog(server))


async def queue_songs(url: str) -> None:
    amy = await Client.open(url, "amy", {"kind": "phoneHello", "browserId": "browser-amy", "name": "Amy"})
    ben = await Client.open(url, "ben", {"kind": "phoneHello", "browserId": "browser-ben", "name": "Ben"})
    for phone, title in ((amy, "Morning Sun"), (ben, "Night Drive"), (amy, "河流")):
        hit = (await aget(f"{url}/api/search?q={urllib.request.quote(title)}"))["library"][0]
        assert await phone.send({"kind": "queueLibrary", "songId": hit["song"]["songId"]}) == {"kind": "accepted"}
    await amy.until(lambda v: v["now"] is not None and len(v["queue"]) == 2)


async def answer_restart(url: str) -> None:
    tv = await Client.open(url, "tv", {"kind": "tvHello"})
    amy = await Client.open(url, "amy", {"kind": "phoneHello", "browserId": "browser-amy", "name": "Amy"})
    ben = await Client.open(url, "ben", {"kind": "phoneHello", "browserId": "browser-ben", "name": "Ben"})
    assert tv.view and tv.view["restartOffer"] and ben.view and ben.view["restartOffer"]
    offered = [e["title"] for e in ben.view["restartOffer"]["entries"]]
    assert offered == ["Morning Sun", "Night Drive", "河流"], "the playing song is saved at the front"
    answers = await asyncio.gather(amy.send({"kind": "resolveRestart", "keep": True}),
                                   ben.send({"kind": "resolveRestart", "keep": False}))
    assert answers == [{"kind": "accepted"}, {"kind": "rejected", "reason": "already_resolved"}]
    v = await ben.until(lambda v: v["restartOffer"] is None and v["now"] is not None)
    assert v["now"]["song"]["title"] == "Morning Sun" and [e["song"]["title"] for e in v["queue"]] == ["Night Drive", "河流"]
    for c in (tv, amy, ben):
        await c.close()


def test_restart_offers_keep_or_new_and_first_answer_wins(tmp_path: Path) -> None:
    with running_server(tmp_path) as url:
        asyncio.run(queue_songs(url))
    with running_server(tmp_path) as url:
        asyncio.run(answer_restart(url))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8080")
    asyncio.run(party(parser.parse_args().url, say))
