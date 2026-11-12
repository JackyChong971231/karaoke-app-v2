"""Append-only log of every party input this run (JSON lines, one file per start). Debugging only:
recovery uses the snapshot, never the journal.

Because `reduce` is pure, `karaoke replay <journal>` re-runs a whole party offline. A bug report from the
party becomes a failing unit test by copying lines.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TextIO

from karaoke import party
from karaoke.party import Input, PartyState, Rejected
from karaoke.shell.codec import decode, encode


class Journal:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._file: TextIO | None = None

    def append(self, inp: Input) -> None:
        if self._file is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._file = open(self.path, "a", encoding="utf-8")
        self._file.write(json.dumps(encode(inp), ensure_ascii=False) + "\n")
        self._file.flush()

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None


def read(path: Path) -> list[Input]:
    return [decode(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def replay(path: Path, initial: PartyState, verbose: bool = False) -> PartyState:
    """Fold reduce over the journal. An exception names the line that broke an invariant."""
    state = initial
    for n, inp in enumerate(read(path), start=1):
        try:
            step = party.reduce(state, inp)
        except Exception as e:
            raise RuntimeError(f"line {n}: {inp!r} raised {e!r}") from e
        if verbose:
            mark = f"rejected {step.outcome.reason}" if isinstance(step.outcome, Rejected) else "ok"
            print(f"{n:5d} {mark:28s} {inp!r}")
        state = step.state
    return state
