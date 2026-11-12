"""Structural checks import-linter cannot express.

- No module outside karaoke.party constructs PartyState, and no module that imports karaoke.party calls
  dataclasses.replace. The reducer stays the only writer of party state.
- web/src/wire/generated.ts is listed in web/.gitignore (it must never be committed and drift).
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "karaoke"
REPO = Path(__file__).resolve().parents[2]


def _modules_outside_party() -> list[tuple[Path, ast.Module]]:
    return [(p, ast.parse(p.read_text(encoding="utf-8"))) for p in SRC.rglob("*.py") if "party" not in p.parts]


def _imports_party(tree: ast.Module) -> bool:
    return any(isinstance(n, ast.ImportFrom) and (n.module or "").startswith("karaoke.party") for n in ast.walk(tree))


def _called_names(tree: ast.Module) -> set[str]:
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            names.add(f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else "")
    return names


def test_only_reduce_builds_party_state() -> None:
    offenders = []
    for path, tree in _modules_outside_party():
        called = _called_names(tree)
        if "PartyState" in called or (_imports_party(tree) and "replace" in called and _uses_dataclass_replace(tree)):
            offenders.append(str(path.relative_to(SRC)))
    assert offenders == [], f"only karaoke.party may build or copy PartyState: {offenders}"


def _uses_dataclass_replace(tree: ast.Module) -> bool:
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module == "dataclasses" and any(a.name == "replace" for a in n.names):
            return True
        if isinstance(n, ast.Attribute) and n.attr == "replace" and isinstance(n.value, ast.Name) and n.value.id == "dataclasses":
            return True
    return False


def test_generated_wire_is_not_committed() -> None:
    ignored = (REPO / "web" / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "src/wire/generated.ts" in ignored
