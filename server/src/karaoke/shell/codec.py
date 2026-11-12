"""JSON <-> party dataclasses, for the journal, party.json, and /test/state.

Every dataclass is written as {"$": ClassName, field: value, ...}. The registry is built by scanning the
party and core modules, so a new input type is journaled with no change here.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Any

from karaoke import core
from karaoke.party import inputs, model

_TYPES: dict[str, type] = {
    name: obj
    for mod in (core, model, inputs)
    for name, obj in vars(mod).items()
    if isinstance(obj, type) and dataclasses.is_dataclass(obj) and obj.__module__ == mod.__name__
}


def encode(x: Any) -> Any:
    if dataclasses.is_dataclass(x) and not isinstance(x, type):
        return {"$": type(x).__name__, **{f.name: encode(getattr(x, f.name)) for f in dataclasses.fields(x)}}
    if isinstance(x, frozenset | set):
        return sorted(encode(v) for v in x)
    if isinstance(x, tuple | list):
        return [encode(v) for v in x]
    if isinstance(x, Mapping):
        return {k: encode(v) for k, v in x.items()}
    return x


def decode(x: Any) -> Any:
    """Lists come back as tuples, which is what every party sequence field holds."""
    if isinstance(x, dict):
        if "$" in x:
            cls = _TYPES[x["$"]]
            return cls(**{k: decode(v) for k, v in x.items() if k != "$"})
        return {k: decode(v) for k, v in x.items()}
    if isinstance(x, list):
        return tuple(decode(v) for v in x)
    return x
