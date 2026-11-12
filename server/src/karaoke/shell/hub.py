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
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from pydantic import TypeAdapter, ValidationError
from starlette.websockets import WebSocket, WebSocketDisconnect

from karaoke import contract as c
from karaoke.core import SingerId
from karaoke.party import Hello, Input, Outcome, Rejected, TvPresence
from karaoke.shell import parse
from karaoke.shell.loop import PartyLoop
from karaoke.songs.catalog import Catalog
from karaoke.songs.library import Library

log = logging.getLogger(__name__)
_client = TypeAdapter(c.ClientMessage)
_POLICY_VIOLATION = 1008
_INTERNAL_ERROR = 1011
_RESUME_MEMORY = 8


@dataclass(eq=False)
class _Conn:
    ws: WebSocket
    role: Literal["phone", "tv"] | None = None
    singer: SingerId | None = None
    last_rev: int | None = None
    outbox: asyncio.Queue[c.Wire | None] = field(default_factory=asyncio.Queue)

    def send(self, msg: c.Wire) -> None:
        self.outbox.put_nowait(msg)

    def close(self) -> None:
        self.outbox.put_nowait(None)


class Hub:
    def __init__(self, loop: PartyLoop, library: Library, catalog: Catalog, protocol: str) -> None:
        self._loop = loop
        self._library = library
        self._catalog = catalog
        self._protocol = protocol
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
            case c.PhoneHello(singer_id=singer_id, name=name):
                conn.role, conn.singer = "phone", SingerId(singer_id)
                self._phones.add(conn)
                await self._loop.submit(Hello(conn.singer, name))
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
                inp = parse.phone_input(command, conn.singer, self._library, self._catalog)
                conn.send(_reply(request_id, await self._submit(inp)))
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
