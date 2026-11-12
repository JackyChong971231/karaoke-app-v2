"""Turn-taking rules. Pure. Private to karaoke.party (called only from reduce.py)."""

from __future__ import annotations

from karaoke.core import SingerId
from karaoke.party.model import EntryId, Fairness, QueueEntry, SavedEntry


def next_round(fairness: Fairness, queue: tuple[QueueEntry, ...], singer: SingerId) -> int:
    """Round for a singer's new song: songs started tonight + songs already queued + 1.

    The now-playing queued song is already counted in `fairness.sung` (counted at start)
    and is no longer in `queue`, so it is neither missing nor double counted.
    """
    queued = sum(1 for e in queue if e.singer == singer)
    return fairness.sung.get(singer, 0) + queued + 1


def with_joined(fairness: Fairness, singer: SingerId) -> Fairness:
    """Append `singer` to join_order if this is their first song tonight. Idempotent."""
    if singer in fairness.join_order:
        return fairness
    return Fairness(join_order=(*fairness.join_order, singer), sung=fairness.sung)


def insert_fairly(queue: tuple[QueueEntry, ...], entry: QueueEntry, join_order: tuple[SingerId, ...]) -> tuple[QueueEntry, ...]:
    """Place a new entry right after the LAST entry whose (round, join index) is smaller.

    The whole queue is scanned, not a sorted prefix, because manual moves mean the queue need not be
    sorted. Existing entries keep their relative order.

    Worked example from the product spec (join order A, B, C):
        A1 B1 B2 B3 B4
        A2 (2,0)  last smaller is B1           -> A1 B1 A2 B2 B3 B4
        C1 (1,2)  last smaller is B1           -> A1 B1 C1 A2 B2 B3 B4
        C2 (2,2)  last smaller is B2           -> A1 B1 C1 A2 B2 C2 B3 B4
    """
    rank = {singer: i for i, singer in enumerate(join_order)}

    def key(e: QueueEntry) -> tuple[int, int]:
        return (e.round, rank[e.singer])

    new_key = key(entry)
    pos = 0
    for i, e in enumerate(queue):
        if key(e) < new_key:
            pos = i + 1
    return (*queue[:pos], entry, *queue[pos:])


def renumber_kept(offer: tuple[SavedEntry, ...], first_entry_id: EntryId) -> tuple[tuple[QueueEntry, ...], Fairness]:
    """Turn a kept queue into tonight's queue "as if the night had just started".

    Order is preserved exactly. Join order and rounds are rebuilt from that order, so a new singer's
    first song lands among the kept round-1 songs.
    """
    join_order: list[SingerId] = []
    counts: dict[SingerId, int] = {}
    entries: list[QueueEntry] = []
    for i, saved in enumerate(offer):
        if saved.singer not in counts:
            join_order.append(saved.singer)
        counts[saved.singer] = counts.get(saved.singer, 0) + 1
        entries.append(QueueEntry(EntryId(first_entry_id + i), saved.song, saved.singer, counts[saved.singer]))
    return tuple(entries), Fairness(join_order=tuple(join_order), sung={})
