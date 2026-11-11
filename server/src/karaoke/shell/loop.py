"""The imperative shell around the pure reducer. One asyncio task; one inbox; no locks.

Every party change in the process goes through `submit` -> inbox -> `reduce`. Concurrent phones are
serialized here by arrival order; because inputs reference IDs, the result of any interleaving is
well defined (and a stale one is a Rejected reply, not a corrupted queue).

After every step the loop RECONCILES the world toward projections of the new state:

    durable(state)             -> Store.save           if changed     (persistence)
    preparation_demand(state)  -> Preparer.set_demand  if changed     (preparation, incl. restart recovery)
    filler_request(state)      -> Library.random_pick -> submit(FillerPicked)   once per token
    views(state, board, clock) -> Hub.publish          if changed     (broadcast)

There is no other way to persist, prepare, or broadcast. A new reducer branch gets all four for free.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from karaoke.party import Input, Outcome, PartyState
from karaoke.shell.journal import Journal
from karaoke.shell.store import Store
from karaoke.songs.library import Library
from karaoke.songs.prepare import Preparer


@dataclass(frozen=True, slots=True)
class _Refresh:
    """Something outside party state changed (preparation board, clock). Re-publish views; no reduce."""


class PartyLoop:
    def __init__(self, state: PartyState, store: Store, journal: Journal, preparer: Preparer,
                 library: Library, join_url: str) -> None:
        self._inbox: asyncio.Queue[tuple[Input | _Refresh, asyncio.Future[Outcome] | None]] = asyncio.Queue()
        raise NotImplementedError

    def attach_hub(self, hub) -> None:
        """Hub and loop reference each other; the hub is attached after construction."""
        raise NotImplementedError

    def submit(self, inp: Input) -> asyncio.Future[Outcome]:
        """Enqueue an input. Callable from the loop thread; Preparer worker threads use
        loop.call_soon_threadsafe(submit, ...). Returns the outcome future for the reply."""
        raise NotImplementedError

    def refresh(self) -> None:
        raise NotImplementedError

    @property
    def state(self) -> PartyState:
        """Read-only, for the harness /test/state endpoint and for views."""
        raise NotImplementedError

    async def run(self) -> None:
        """TODO pseudocode:
            reconcile()                       # first demand after boot = restart recovery of preparation
            while True:
                item, fut = await inbox.get()
                if item is not _Refresh:
                    journal.append(item)              # before reduce, so a crashing input is on record
                    step = reduce(state, item)        # pure; an exception here is a bug -> log, keep old state
                    state = step.state
                    fut and fut.set_result(step.outcome)
                reconcile()
        """
        raise NotImplementedError

    def _reconcile(self) -> None:
        """TODO pseudocode:
            snap = durable(state);            if snap != last_snap: store.save(snap); last_snap = snap
            demand = preparation_demand(state)
            if demand != last_demand: preparer.set_demand("party", [PrepRequest(s) for s in demand])
            req = filler_request(state)
            if req and (req.token, library.count()) != last_filler_attempt:
                last_filler_attempt = (req.token, library.count())   # retry only when the library grows
                song = library.random_pick(req.avoid); song and submit(FillerPicked(req.token, song))
            rev += 1 if either view changed; hub.publish(phone_view(...), tv_view(...))
        """
        raise NotImplementedError
