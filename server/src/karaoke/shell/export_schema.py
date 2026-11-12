"""Dump the wire contract as JSON Schema for TypeScript codegen.

    uv run python -m karaoke.shell.export_schema --out ../web/src/wire/schema.json

Called by web/package.json `gen:wire`, which `predev`, `prebuild`, and `pretypecheck` run first.
The file carries `x-protocol`, the hash the server also sends in ServerHello, so gen-wire can bake it into
the page and a page built against another contract reloads instead of talking past the server.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from functools import cache
from pathlib import Path
from typing import Any

from karaoke.contract import Contract


def schema() -> dict[str, Any]:
    """Contract.model_json_schema(by_alias=True, mode="serialization"), with $defs sorted for a stable diff."""
    s = Contract.model_json_schema(by_alias=True, mode="serialization")
    s["$defs"] = dict(sorted(s["$defs"].items()))
    return s


@cache
def protocol_hash() -> str:
    canonical = json.dumps(schema(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    doc = {"x-protocol": protocol_hash(), **schema()}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
