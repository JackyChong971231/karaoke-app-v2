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
import urllib.error
import urllib.parse
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
    log(f"now playing: {now['song']['title']!r} by {now['singerName']} (first READY entry; Amy has had her turn)")
    log(f"queue after: {letters(v)}  readiness: {[e['readiness'].get('stage', 'ready') for e in v['queue']]}")
    assert now["song"]["title"] == "Night Drive" and now["singerName"] == "Amy" and letters(v) == "BABBB"
    tv_view = await tv.until(lambda t: t["play"] and t["play"]["playId"] == now["playId"])
    assert tv_view["upNext"]["singerName"] == "Ben"

    await tv.ws.send(json.dumps({"kind": "clock", "playId": now["playId"], "positionS": 4.25, "paused": False}))
    await asyncio.wait_for(_until(lambda: amy.clock is not None and ben.clock is not None), 5)
    assert amy.clock is not None
    log(f"TV clock relayed to phones: positionS={amy.clock['positionS']}")

    v = await amy.until(lambda v: v["queue"][0]["readiness"]["kind"] == "ready", timeout=30)
    log(f"Ben's first song finished preparing: {v['queue'][0]['song']['title']!r} is ready at the front")
    ended = await tv.send({"kind": "trackEnded", "playId": now["playId"]}, envelope="tvCommand")
    assert ended == {"kind": "accepted"}
    v = await amy.until(lambda v: v["now"]["playId"] == now["playId"] + 1)
    log(f"TV reports track ended -> now playing {v['now']['song']['title']!r} by {v['now']['singerName']}")
    assert v["now"]["song"]["title"] == "Second Fake Hit" and v["now"]["singerName"] == "Ben"
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
    assert "fairness" not in state["party"], "turn order is rebuilt from the queue, never stored"


def back_to_back(view: dict[str, Any], phone_of: dict[str, str]) -> list[str]:
    """Places where one phone has two songs in a row while another phone still has a song waiting after them.
    The song playing now counts as the first in line. `phone_of` maps a singer name to its phone."""
    singing = view["now"]["singerName"] if view["now"] else None
    q = [e["singerId"] for e in view["queue"]]
    names = [e["singerName"] for e in view["queue"]]
    if singing:
        q, names = [phone_of[singing], *q], [f"{singing} (singing)", *names]
    return [f"{names[i]} at {i + 1},{i + 2}" for i in range(len(q) - 1)
            if q[i] == q[i + 1] and any(x != q[i] for x in q[i + 2:])]


async def five_phone_party(url: str, log: Callable[[str], None]) -> None:
    """Spec "Queue fairness" (2026-11-15, v1's rotation): however songs are added, removed, moved, or played,
    the queue never puts one phone twice in a row while another phone is waiting."""
    tv = await Client.open(url, "tv", {"kind": "tvHello"})
    phones = {n: await Client.open(url, n, {"kind": "phoneHello", "browserId": f"b-{n}", "name": n})
              for n in ("Jacky", "K", "Beauty", "ooo")}
    ooo_tab = await Client.open(url, "ooo-tab", {"kind": "phoneHello", "browserId": "b-tab", "name": "ooo2"},
                                device="ooo")
    j, k, b, o = phones["Jacky"], phones["K"], phones["Beauty"], phones["ooo"]
    filler = (await j.until(lambda v: v["now"] is not None))["now"]
    assert await j.send({"kind": "setPaused", "playId": filler["playId"], "paused": True}) == {"kind": "accepted"}

    async def pick(title: str) -> dict[str, Any]:
        found = await aget(f"{url}/api/search?q=fake")
        song = next(s for s in found["online"]["songs"] if s["title"] == title)
        choice = await aget(f"{url}/api/video-choice?key={song['onlineKey']}")
        return {"kind": "queuePick", "pickId": choice["pickId"]}

    async def library(title: str) -> dict[str, Any]:
        hit = (await aget(f"{url}/api/search?q={urllib.parse.quote(title)}"))["library"][0]
        return {"kind": "queueLibrary", "songId": hit["song"]["songId"]}

    async def queue(*plan: tuple[Client, dict[str, Any]]) -> None:
        for phone, cmd in plan:
            assert await phone.send(cmd) == {"kind": "accepted"}

    phone_of: dict[str, str] = {}

    async def check(step: str, length: int | None = None) -> dict[str, Any]:
        v = await j.until(lambda v: length is None or len(v["queue"]) == length)
        phone_of.update({e["singerName"]: e["singerId"] for e in v["queue"]})
        now = v["now"]["singerName"] or "filler"
        log(f"{step:<58} now={now:<7} queue: {' '.join(e['singerName'] for e in v['queue'])}")
        assert not back_to_back(v, phone_of), (step, back_to_back(v, phone_of))
        return v

    # Jacky queues a pile first, alone, as the host does before guests arrive.
    await queue((j, await library("Morning Sun")), (j, await library("河流")), (j, await pick("Fake Song One")))
    await check("Jacky queues 3 alone", 3)

    # Everyone queues at the same moment, songs ready and still preparing, mixed.
    burst = [(k, await pick("Second Fake Hit")), (k, await library("Night Drive")), (b, await library("河流")),
             (o, await pick("Complicated Fake")), (ooo_tab, await library("Morning Sun")), (k, await library("河流")),
             (b, await pick("Fake Song One"))]
    await asyncio.gather(*(queue(x) for x in burst))
    await check("K, Beauty, ooo + ooo's 2nd browser queue at once", 10)

    # ooo renames to look like someone new and queues again. Still one phone.
    assert await o.send({"kind": "rename", "name": "Not ooo"}) == {"kind": "accepted"}
    await queue((o, await library("Night Drive")))
    await check("ooo renames and queues again", 11)

    # Songs play: skip the filler, then the TV ends songs one by one. Each start rebuilds the rotation.
    assert await b.send({"kind": "skip", "playId": filler["playId"]}) == {"kind": "accepted"}
    v = await check("filler skipped, first ready song plays", 10)
    for n in range(3):
        play = v["now"]["playId"]
        assert await tv.send({"kind": "trackEnded", "playId": play}, envelope="tvCommand") == {"kind": "accepted"}
        v = await j.until(lambda x: x["now"] is not None and x["now"]["playId"] != play)
        v = await check(f"song {n + 1} ends")

    # A late guest joins with three songs.
    mei = await Client.open(url, "Mei", {"kind": "phoneHello", "browserId": "b-mei", "name": "Mei"})
    size = len(v["queue"])
    await queue((mei, await library("Morning Sun")), (mei, await library("河流")), (mei, await library("Night Drive")))
    v = await check("Mei arrives late and queues 3", size + 3)

    # K removes one song, Beauty moves her song to the front, then Jacky queues again.
    mine = next(e for e in v["queue"] if e["singerName"] == "K")
    assert await k.send({"kind": "remove", "entryId": mine["entryId"]}) == {"kind": "accepted"}
    v = await check("K removes a song", size + 2)
    beauty = next(e for e in v["queue"] if e["singerName"] == "Beauty")
    assert await b.send({"kind": "move", "entryId": beauty["entryId"], "to": {"at": "front"}}) == {"kind": "accepted"}
    v = await j.until(lambda x: x["queue"][0]["entryId"] == beauty["entryId"])
    await queue((j, await library("Night Drive")))
    v = await check("Beauty moves hers to the front, Jacky queues again", size + 3)
    assert v["queue"][0]["entryId"] == beauty["entryId"], "a song moved to the front stays first"

    # Play the rest of the night out.
    while v["queue"]:
        if v["now"]["isFiller"]:
            v = await j.until(lambda x: any(e["readiness"]["kind"] == "ready" for e in x["queue"]), timeout=60)
        play = v["now"]["playId"]
        assert await tv.send({"kind": "trackEnded", "playId": play}, envelope="tvCommand") == {"kind": "accepted"}
        v = await j.until(lambda x: x["now"] is not None and x["now"]["playId"] != play, timeout=30)
        v = await check("song ends")
    for c in (tv, *phones.values(), ooo_tab, mei):
        await c.close()


def test_five_phones_never_queue_one_singer_back_to_back(server: str) -> None:
    asyncio.run(five_phone_party(server, say))


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


def post(url: str, body: dict[str, Any], device: str) -> Any:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={
        "content-type": "application/json", "Cookie": f"karaoke-test-device={device}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def get_as(url: str, device: str) -> Any:
    req = urllib.request.Request(url, headers={"Cookie": f"karaoke-test-device={device}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


async def favourites(url: str) -> None:
    """Spec "Favourite songs": hearts from search, queue from the list, and the list survives a browser that starts
    empty after the laptop's address changed."""
    amy = await Client.open(url, "amy", {"kind": "phoneHello", "browserId": "browser-1", "name": "Amy"})
    online = (await aget(f"{url}/api/search?q=fake"))["online"]["songs"]
    one = next(s for s in online if s["title"] == "Fake Song One")
    lib = (await aget(f"{url}/api/search?q=Morning%20Sun"))["library"][0]["song"]
    add = f"{url}/api/favourites/add"
    await asyncio.to_thread(post, add, {"browserId": "browser-1", "name": "Amy",
                                        "ref": {"kind": "online", "onlineKey": one["onlineKey"]}}, "amy")
    favs = await asyncio.to_thread(post, add, {"browserId": "browser-1", "name": "Amy",
                                               "ref": {"kind": "song", "songId": lib["songId"]}}, "amy")
    assert [(f["song"]["songId"], f["ready"]) for f in favs["songs"]] == [("fklib000001", True), ("fkomv000001", False)]

    assert await amy.send({"kind": "queueFavourite", "songId": "fkomv000001"}) == {"kind": "accepted"}
    assert await amy.send({"kind": "queueFavourite", "songId": "not-mine"}) == \
        {"kind": "rejected", "reason": "unknown_entry"}
    v = await amy.until(lambda v: any(e["song"]["songId"] == "fkomv000001" for e in v["queue"]))
    assert v["queue"][0]["singerName"] == "Amy"

    # The laptop's address changed: the phone's browser is empty, so it has a new browser id and no name yet.
    offer = await asyncio.to_thread(get_as, f"{url}/api/favourites/offer", "amy")
    assert {k: offer[k] for k in ("kind", "name", "count")} == {"kind": "offer", "name": "Amy", "count": 2}
    assert (await asyncio.to_thread(get_as, f"{url}/api/favourites/offer", "stranger"))["kind"] == "none"
    by_name = await asyncio.to_thread(get_as, f"{url}/api/favourites/offer?name=amy", "stranger")
    assert by_name["kind"] == "offer"
    restored = await asyncio.to_thread(post, f"{url}/api/favourites/claim",
                                       {"token": offer["token"], "browserId": "browser-2", "name": "Amy"}, "amy")
    assert len(restored["songs"]) == 2
    assert (await aget(f"{url}/api/favourites?browser=browser-1"))["songs"] == []
    await amy.close()


def test_favourites_queue_and_restore(server: str) -> None:
    asyncio.run(favourites(server))


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


def test_lyrics_sites_over_the_wire(server: str) -> None:
    """Spec "Read the lyrics from a lyrics site": the phone asks for a library song's sites, then each site's
    answer. The fake world gives one answer kind per site."""
    sites = get(f"{server}/api/site-lyrics?song=fklib000002")
    assert sites == {"sites": ["genius", "kkbox", "lrclib", "utanet"]}  # seeded as English, so Genius first
    text = get(f"{server}/api/site-lyrics?song=fklib000002&site=lrclib")
    assert text["kind"] == "text" and text["pageUrl"] is None and "河流 line one" in text["text"]
    assert get(f"{server}/api/site-lyrics?song=fklib000002&site=kkbox") == {
        "kind": "link", "site": "kkbox", "pageUrl": "https://www.kkbox.com/tw/tc/song/fakeSong", "found": True}
    assert get(f"{server}/api/site-lyrics?song=fklib000002&site=utanet") == {"kind": "none", "site": "utanet"}
    for bad, status in (("song=nosuchsong", 404), ("song=fklib000002&site=mojim", 400)):
        with pytest.raises(urllib.error.HTTPError) as e:
            get(f"{server}/api/site-lyrics?{bad}")
        assert e.value.code == status
