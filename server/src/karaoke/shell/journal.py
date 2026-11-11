"""Append-only log of every party input this run (JSON lines, one file per start). Debugging only:
recovery uses the snapshot, never the journal.

Because `reduce` is pure, `karaoke replay <journal>` re-runs a whole party offline and stops at the input
where an invariant broke. A bug report from the party becomes a failing unit test by copying lines.
"""

from __future__ import annotations

from pathlib import Path

from karaoke.party import Input, PartyState


class Journal:
    def __init__(self, path: Path) -> None:
        raise NotImplementedError

    def append(self, inp: Input) -> None:
        raise NotImplementedError


def replay(path: Path, initial: PartyState) -> PartyState:
    """Fold reduce over the journal; check invariants after each step (see tests/test_party_invariants.py)."""
    raise NotImplementedError
