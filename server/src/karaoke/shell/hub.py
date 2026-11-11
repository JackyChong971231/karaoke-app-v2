"""WebSocket connections. Owns: who is connected, in which role, and the TV's last clock report.

Does not own party state. It parses incoming messages, hands party inputs to the PartyLoop, sends the
reply back to the sender, and publishes whatever snapshot the loop gives it.
"""

from __future__ import annotations

from collections.abc import Mapping

from karaoke import contract as c
from karaoke.shell.loop import PartyLoop  # same package: hub and loop are both the imperative shell


class Hub:
    def __init__(self, loop: PartyLoop) -> None:
        raise NotImplementedError

    async def serve(self, websocket) -> None:
        """One connection, for its lifetime.

        TODO pseudocode:
            first = ClientMessage.parse(await recv())
            PhoneHello(singer_id, name) -> role phone, bound singer = singer_id;
                                           loop.submit(Hello(singer_id, name)); send latest PhoneViewMsg
            TvHello                     -> role tv; if another tv is connected: send it SupersededMsg, close it;
                                           loop.submit(TvPresence(True)); send latest TvViewMsg
            then for each message:
                PhoneCommandMsg on a phone -> x = parse.phone_input(cmd, bound singer, ...)
                                              outcome = Unresolvable -> Rejected(reason), else await loop.submit(x)
                                              send ReplyMsg(request_id, outcome)
                TvCommandMsg on the tv     -> same with parse.tv_input
                ClockReport on the tv      -> remember (play_id -> position); fan out ClockMsg to phones (no reduce)
                anything else for the role -> close with 1008 (policy violation). Roles cannot cross.
            on close of the current tv: loop.submit(TvPresence(False))
        """
        raise NotImplementedError

    def resume_positions(self) -> Mapping[int, float]:
        raise NotImplementedError

    def publish(self, phone: c.PhoneView, tv: c.TvView) -> None:
        """Send each snapshot to its role, only if its rev changed since the last send to that socket."""
        raise NotImplementedError
