"""Turn-taking rules. Pure. Private to karaoke.party (called only from reduce.py)."""

from __future__ import annotations

from karaoke.core import SingerId
from karaoke.party.model import EntryId, Fairness, QueueEntry, SavedEntry


def next_round(fairness: Fairness, queue: tuple[QueueEntry, ...], singer: SingerId) -> int:
    """Round for a singer's new song: songs started tonight + songs already queued + 1.

    The now-playing queued song is already counted in `fairness.sung` (counted at start),
    so it is neither missing nor double counted.
    """
    raise NotImplementedError


def with_joined(fairness: Fairness, singer: SingerId) -> Fairness:
    """Append `singer` to join_order if this is their first song tonight. Idempotent."""
    raise NotImplementedError


def insert_fairly(queue: tuple[QueueEntry, ...], entry: QueueEntry, join_order: tuple[SingerId, ...]) -> tuple[QueueEntry, ...]:
    """Place a new entry at its fair position. Existing entries keep their relative order.

    TODO pseudocode (spec rule, technical spec "Data model"):
        rank = {singer: i for i, singer in enumerate(join_order)}
        key  = lambda e: (e.round, rank[e.singer])
        # Right after the LAST entry whose key is smaller. Scan the whole queue, not a prefix,
        # because manual reorders mean the queue need not be sorted.
        pos = 0
        for i, e in enumerate(queue):
            if key(e) < key(entry):
                pos = i + 1
        return queue[:pos] + (entry,) + queue[pos:]

    Worked example from the product spec (join order A, B, C):
        A1                 -> [A1]
        B1 (1,1)           -> [A1 B1]
        B2 B3 B4           -> [A1 B1 B2 B3 B4]
        A2 (2,0)  last smaller is B1           -> [A1 B1 A2 B2 B3 B4]
        C1 (1,2)  last smaller is B1           -> [A1 B1 C1 A2 B2 B3 B4]
        C2 (2,2)  last smaller is B2           -> [A1 B1 C1 A2 B2 C2 B3 B4]
    History example: A sung 3, D joins. D1 key (1,1) < A4 key (4,0), so D sings first.

    Every singer in `queue` and `entry.singer` must be in `join_order`; reduce guarantees it by
    calling with_joined before insert_fairly. A KeyError here is a reducer bug, not bad input.
    """
    raise NotImplementedError


def renumber_kept(offer: tuple[SavedEntry, ...], first_entry_id: EntryId) -> tuple[tuple[QueueEntry, ...], Fairness]:
    """Turn a kept queue into tonight's queue 'as if the night had just started'.

    TODO pseudocode:
        join_order = singers in order of first appearance in `offer`
        per-singer counter c[s] starts at 0
        for each saved entry in order: c[s] += 1; QueueEntry(id=next id, round=c[s], ...)
        return entries (same order as offer), Fairness(join_order, sung={})

    Order is preserved exactly (spec: "A kept queue keeps its order"). Rounds and join order are
    rebuilt from that order, so a new singer's first song lands among the kept round-1 songs.
    """
    raise NotImplementedError
