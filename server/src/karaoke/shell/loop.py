"""The imperative shell around the pure reducer. One asyncio task; one inbox; no locks.

Every party change in the process goes through `submit` -> inbox -> `reduce`. Concurrent phones are
serialized here by arrival order; because inputs reference IDs, the result of any interleaving is
well defined (and a stale one is a Rejected reply, not a corrupted queue).

After every step the loop RECONCILES the world toward projections of the new state:

    durable(state)             -> Store.save           if changed     (persistence)
    preparation_demand(state)  -> Preparer.set_demand  if changed     (preparation, incl. restart recovery)
    filler_request(state)      -> Library.random_pick -> submit(FillerPicked)   once per token and library size
    views(state, board, clock) -> Hub.publish          if changed     (broadcast)

There is no other way to persist, prepare, or broadcast. A new reducer branch gets all four for free.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from karaoke import contract as c
from karaoke.core import SongId
from karaoke import party
from karaoke.party import (
    DurableSnapshot, FillerPicked, Input, Outcome, PartyState, Playing, durable, filler_request, preparation_demand,
)
from karaoke.shell import views
from karaoke.shell.journal import Journal
from karaoke.shell.store import Store
from karaoke.songs.library import Library
from karaoke.songs.prepare import Preparer, PrepRequest

log = logging.getLogger(__name__)


class Publisher(Protocol):
    def publish(self, phone: c.PhoneView, tv: c.TvView) -> None: ...
    def resume_positions(self) -> Mapping[int, float]: ...


@dataclass(frozen=True, slots=True)
class _Refresh:
    """Something outside party state changed (preparation board, clock). Re-publish views; no reduce."""


class PartyLoop:
    def __init__(self, state: PartyState, store: Store, journal: Journal, preparer: Preparer,
                 library: Library, join_url: str) -> None:
        self._inbox: asyncio.Queue[tuple[Input | _Refresh, asyncio.Future[Outcome] | None]] = asyncio.Queue()
        self._state = state
        self._store = store
        self._journal = journal
        self._preparer = preparer
        self._library = library
        self.join_url = join_url
        self._hub: Publisher | None = None
        self._last_snap: DurableSnapshot | None = None
        self._last_demand: tuple[object, ...] | None = None
        self._last_filler_attempt: tuple[int, int] | None = None
        self._rev = 0
        self._last_views: tuple[c.PhoneView, c.TvView] | None = None
        self._flag_cache: dict[SongId, bool] = {}
        self._refresh_pending = False

    def attach_hub(self, hub: Publisher) -> None:
        """Hub and loop reference each other; the hub is attached after construction."""
        self._hub = hub

    def submit(self, inp: Input) -> asyncio.Future[Outcome]:
        """Enqueue an input. Call from the event loop thread. Returns the outcome future for the reply."""
        fut: asyncio.Future[Outcome] = asyncio.get_running_loop().create_future()
        self._inbox.put_nowait((inp, fut))
        return fut

    def refresh(self) -> None:
        if not self._refresh_pending:
            self._refresh_pending = True
            self._inbox.put_nowait((_Refresh(), None))

    @property
    def state(self) -> PartyState:
        return self._state

    def views(self) -> tuple[c.PhoneView, c.TvView] | None:
        return self._last_views

    async def run(self) -> None:
        self._reconcile()
        while True:
            item, fut = await self._inbox.get()
            if isinstance(item, _Refresh):
                self._refresh_pending = False
            else:
                self._journal.append(item)
                try:
                    step = party.reduce(self._state, item)
                except Exception as e:
                    log.exception("reduce raised on %r; state unchanged", item)
                    if fut is not None and not fut.done():
                        fut.set_exception(e)
                    continue
                self._state = step.state
                if fut is not None and not fut.done():
                    fut.set_result(step.outcome)
            try:
                self._reconcile()
            except Exception:
                log.exception("reconcile failed; will retry after the next input")

    def _reconcile(self) -> None:
        state = self._state

        snap = durable(state)
        if snap != self._last_snap:
            self._store.save(snap)
            self._last_snap = snap

        demand = preparation_demand(state)
        if demand != self._last_demand:
            self._last_demand = demand
            self._preparer.set_demand("party", [PrepRequest(s) for s in demand])

        req = filler_request(state)
        if req is not None:
            attempt = (req.token, self._library.count())
            if attempt != self._last_filler_attempt:
                self._last_filler_attempt = attempt
                song = self._library.random_pick(req.avoid, req.recent)
                if song is not None:
                    self.submit(FillerPicked(req.token, song))

        self._publish(state)

    def _publish(self, state: PartyState) -> None:
        if self._hub is None:
            return
        flagged = self._flagged(state)
        phone = views.phone_view(0, state, self._preparer.board(), self._preparer.device, flagged)
        tv = views.tv_view(0, state, self._hub.resume_positions(), self.join_url, flagged)
        last = self._last_views
        if last is None or phone != last[0].model_copy(update={"rev": 0}) or tv != last[1].model_copy(update={"rev": 0}):
            self._rev += 1
            self._last_views = (phone.model_copy(update={"rev": self._rev}), tv.model_copy(update={"rev": self._rev}))
        assert self._last_views is not None
        self._hub.publish(*self._last_views)

    def _flagged(self, state: PartyState) -> frozenset[SongId]:
        """Songs whose lyrics were transcribed. A library song's lyrics source never changes, so it is cached."""
        songs = [e.song.id for e in state.queue if e.song.id in state.ready]
        if isinstance(state.now, Playing):
            songs.append(state.now.song.id)
        out: set[SongId] = set()
        for s in songs:
            if s not in self._flag_cache:
                rec = self._library.get(s)
                if rec is None:
                    continue
                self._flag_cache[s] = rec.lyrics_source == "transcribed"
            if self._flag_cache[s]:
                out.add(s)
        return frozenset(out)
