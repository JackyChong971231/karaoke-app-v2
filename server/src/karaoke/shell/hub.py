"""WebSocket connections. Owns: who is connected, in which role, and the TV's last clock report.

Does not own party state. It parses incoming messages, hands party inputs to the PartyLoop, sends the
reply back to the sender, and publishes whatever snapshot the loop gives it.

Each connection has one outbox drained by one writer task, so a sender always receives the snapshot that
reflects its command before the reply to it (the loop publishes before the reply future's callback runs).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal

from pydantic import TypeAdapter, ValidationError
from starlette.requests import HTTPConnection
from starlette.websockets import WebSocket, WebSocketDisconnect

from karaoke import contract as c
from karaoke.core import SingerId, SongId, SongMeta
from karaoke.party import Hello, Input, Outcome, Playing, Rejected, TvPresence
from karaoke.shell import parse
from karaoke.shell.loop import PartyLoop
from karaoke.songs.catalog import Catalog
from karaoke.songs.favourites import Favourites
from karaoke.songs.library import Library

log = logging.getLogger(__name__)
_client = TypeAdapter(c.ClientMessage)
_POLICY_VIOLATION = 1008
_INTERNAL_ERROR = 1011
_RESUME_MEMORY = 8


LAPTOP = SingerId("net:laptop")
TEST_DEVICE_COOKIE = "karaoke-test-device"
"""Fake world only: tests run every phone from one computer, so a cookie stands in for each phone's address."""


def device_singer(host: str | None, laptop_addresses: frozenset[str]) -> SingerId:
    """A singer is a phone, recognised by its address on the home Wi-Fi, not by the ID its browser stores.
    A private tab, a cleared browser, or another browser on the same phone is the same singer. Any browser on
    the laptop itself (the control page) is one singer, `net:laptop`."""
    if not host:
        return LAPTOP
    if host.startswith("::ffff:"):
        host = host.removeprefix("::ffff:")
    if host in laptop_addresses:
        return LAPTOP
    return SingerId(f"net:{host}")


@dataclass(eq=False)
class _Conn:
    ws: WebSocket
    role: Literal["phone", "tv"] | None = None
    singer: SingerId | None = None
    name: str | None = None
    """This browser's current name. Queued songs carry it."""
    browser_id: str | None = None
    last_rev: int | None = None
    outbox: asyncio.Queue[c.Wire | None] = field(default_factory=asyncio.Queue)

    def send(self, msg: c.Wire) -> None:
        self.outbox.put_nowait(msg)

    def close(self) -> None:
        self.outbox.put_nowait(None)


class Hub:
    def __init__(self, loop: PartyLoop, library: Library, catalog: Catalog, protocol: str,
                 laptop_addresses: frozenset[str] = frozenset({"127.0.0.1", "::1"}), test_devices: bool = False,
                 favourites: Favourites | None = None) -> None:
        self._loop = loop
        self.favourites = favourites
        self._library = library
        self._catalog = catalog
        self._protocol = protocol
        self._laptop_addresses = laptop_addresses
        self._test_devices = test_devices
        self._phones: set[_Conn] = set()
        self._tv: _Conn | None = None
        self._positions: dict[int, float] = {}
        self._latest: tuple[c.PhoneView, c.TvView] | None = None

    async def serve(self, websocket: WebSocket) -> None:
        """One connection, for its lifetime."""
        await websocket.accept()
        conn = _Conn(websocket)
        writer = asyncio.create_task(self._write(conn))
        conn.send(c.ServerHello(kind="serverHello", protocol=self._protocol))
        try:
            await self._hello(conn, _client.validate_json(await websocket.receive_text()))
            while True:
                await self._handle(conn, _client.validate_json(await websocket.receive_text()))
        except WebSocketDisconnect:
            pass
        except (ValidationError, _RoleViolation) as e:
            log.warning("closing %s connection: %s", conn.role or "unknown", e)
            await _close(websocket, _POLICY_VIOLATION)
        except Exception:
            log.exception("websocket handler failed")
            await _close(websocket, _INTERNAL_ERROR)
        finally:
            self._phones.discard(conn)
            if self._tv is conn:
                self._tv = None
                self._loop.submit(TvPresence(False))
            conn.close()
            await writer

    async def _hello(self, conn: _Conn, msg: c.PhoneHello | c.TvHello | c.PhoneCommandMsg | c.TvCommandMsg | c.ClockReport) -> None:
        match msg:
            case c.PhoneHello(browser_id=browser_id, name=name):
                conn.role, conn.singer = "phone", self.device_of(conn.ws)
                conn.name, conn.browser_id = name.strip(), browser_id
                if self.favourites is not None:
                    self.favourites.seen(browser_id, conn.name, conn.singer)
                self._phones.add(conn)
                await self._loop.submit(Hello(conn.singer, name))
                conn.send(c.YouMsg(kind="you", singer_id=conn.singer))
            case c.TvHello():
                conn.role = "tv"
                old, self._tv = self._tv, conn
                if old is not None:
                    old.send(c.SupersededMsg(kind="superseded"))
                    old.close()
                await self._loop.submit(TvPresence(True))
            case _:
                raise _RoleViolation(f"expected a hello, got {msg.kind}")
        self._send_latest(conn)

    async def _handle(self, conn: _Conn, msg: c.PhoneHello | c.TvHello | c.PhoneCommandMsg | c.TvCommandMsg | c.ClockReport) -> None:
        match msg:
            case c.PhoneCommandMsg(request_id=request_id, command=command) if conn.role == "phone":
                assert conn.singer is not None
                inp = parse.phone_input(command, conn.singer, self._library, self._catalog, conn.name,
                                        self._favourite_lookup(conn))
                outcome = await self._submit(inp)
                if isinstance(command, c.RenameCmd) and not isinstance(outcome, Rejected):
                    conn.name = command.name.strip()
                conn.send(_reply(request_id, outcome))
            case c.TvCommandMsg(request_id=request_id, command=command) if conn.role == "tv":
                conn.send(_reply(request_id, await self._submit(parse.tv_input(command))))
            case c.ClockReport(play_id=play_id, position_s=position_s, paused=paused) if conn.role == "tv":
                self._remember_position(play_id, position_s)
                relay = c.ClockMsg(kind="clock", play_id=play_id, position_s=position_s, paused=paused,
                                   server_time_ms=int(time.time() * 1000))
                for phone in self._phones:
                    phone.send(relay)
            case _:
                raise _RoleViolation(f"{msg.kind} is not allowed for role {conn.role}")

    def device_of(self, conn: HTTPConnection) -> SingerId:
        """The phone a WebSocket or HTTP request comes from. Also the address favourites remember."""
        if self._test_devices and (fake := conn.cookies.get(TEST_DEVICE_COOKIE)):
            return SingerId(f"net:{fake}")
        return device_singer(conn.client.host if conn.client else None, self._laptop_addresses)

    def known_song(self, song: SongId) -> SongMeta | None:
        """A song the party already holds by video id: playing or queued. For favouriting a queued online song."""
        state = self._loop.state
        if isinstance(state.now, Playing) and state.now.song.id == song:
            return state.now.song
        return next((e.song for e in state.queue if e.song.id == song), None)

    def _favourite_lookup(self, conn: _Conn) -> Callable[[SongId], SongMeta | None]:
        favourites, browser = self.favourites, conn.browser_id
        if favourites is None or browser is None:
            return lambda _: None
        return lambda song: favourites.get(browser, song)

    async def _submit(self, inp: Input | parse.Unresolvable) -> Outcome:
        if isinstance(inp, parse.Unresolvable):
            return Rejected(inp.reason)
        return await self._loop.submit(inp)

    def _remember_position(self, play_id: int, position_s: float) -> None:
        self._positions[play_id] = position_s
        for old in sorted(self._positions)[:-_RESUME_MEMORY]:
            del self._positions[old]

    def resume_positions(self) -> Mapping[int, float]:
        return dict(self._positions)

    def publish(self, phone: c.PhoneView, tv: c.TvView) -> None:
        """Send each snapshot to its role, only if its rev changed since the last send to that socket."""
        self._latest = (phone, tv)
        for conn in [*self._phones, *([self._tv] if self._tv else [])]:
            self._send_latest(conn)

    def _send_latest(self, conn: _Conn) -> None:
        if self._latest is None:
            return
        phone, tv = self._latest
        if conn.role == "phone" and conn.last_rev != phone.rev:
            conn.last_rev = phone.rev
            conn.send(c.PhoneViewMsg(kind="phoneView", view=phone))
        elif conn.role == "tv" and conn.last_rev != tv.rev:
            conn.last_rev = tv.rev
            conn.send(c.TvViewMsg(kind="tvView", view=tv))

    @staticmethod
    async def _write(conn: _Conn) -> None:
        while (msg := await conn.outbox.get()) is not None:
            try:
                await conn.ws.send_text(msg.model_dump_json(by_alias=True))
            except Exception:
                break
        await _close(conn.ws, 1000)


class _RoleViolation(Exception):
    pass


def _reply(request_id: int, outcome: Outcome) -> c.ReplyMsg:
    wire: c.Accepted | c.Rejected = (
        c.Rejected(kind="rejected", reason=outcome.reason) if isinstance(outcome, Rejected)
        else c.Accepted(kind="accepted")
    )
    return c.ReplyMsg(kind="reply", request_id=request_id, outcome=wire)


async def _close(ws: WebSocket, code: int) -> None:
    try:
        await ws.close(code)
    except Exception:
        pass
