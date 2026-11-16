"""Turn-taking rule (v1's rotation). Pure. Private to karaoke.party (called only from reduce.py)."""

from __future__ import annotations

from collections.abc import Set

from karaoke.core import SingerId, SongId
from karaoke.party.model import QueueEntry


def next_up(queue: tuple[QueueEntry, ...], ready: Set[SongId], last: SingerId | None) -> QueueEntry | None:
    """The song to play next, or None to wait (a filler plays). A turn belongs to a singer, not to one song.

    Walk the singers in queue order. The first singer with any ready song sings their earliest ready song, even
    if their first song is still preparing. A singer with nothing ready is passed over and stays first in line.
    `last`, who sang the most recent queued song, never sings twice in a row while anyone else has a song
    queued: the TV waits for the others instead (user, 2026-11-16: "just wait, keep it simple").
    """
    others_waiting = any(e.singer != last for e in queue)
    passed: set[SingerId] = set()
    for e in queue:
        if e.singer in passed or (e.singer == last and others_waiting):
            continue
        passed.add(e.singer)
        mine = next((x for x in queue if x.singer == e.singer and x.song.id in ready), None)
        if mine is not None:
            return mine
    return None


def rotated(queue: tuple[QueueEntry, ...], last: SingerId | None) -> tuple[QueueEntry, ...]:
    """Rebuild the queue as a rotation: one song per singer per turn.

    Singers take turns in the order they first appear in `queue`, except `last` (who sang the most recent queued
    song, possibly still singing it), who has just had a turn and goes last. Each singer's songs keep the order
    they have in `queue`. Nothing else counts: songs sung earlier tonight earn no extra turns, so nobody catches
    up back to back.

    User example (00-product.md): A B B B B A C  ->  A B C A B B B
    """
    by_singer: dict[SingerId, list[QueueEntry]] = {}
    for e in queue:
        by_singer.setdefault(e.singer, []).append(e)
    if last in by_singer:
        by_singer[last] = by_singer.pop(last)
    out: list[QueueEntry] = []
    for turn in range(max((len(songs) for songs in by_singer.values()), default=0)):
        out.extend(songs[turn] for songs in by_singer.values() if turn < len(songs))
    return tuple(out)
