"""Dump the wire contract as JSON Schema for TypeScript codegen.

    uv run python -m karaoke.shell.export_schema --out ../web/src/wire/schema.json

Called by web/package.json `gen:wire`, which `predev`, `prebuild`, and `pretypecheck` run first.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from karaoke.contract import Contract


def schema() -> dict:
    """Contract.model_json_schema(by_alias=True, mode="serialization"), with $defs sorted for a stable diff.
    Every Literal becomes an enum; every Annotated union becomes oneOf + discriminator.mapping."""
    raise NotImplementedError


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    raise NotImplementedError


if __name__ == "__main__":
    main()
