"""Structural checks import-linter cannot express.

- No module outside karaoke.party constructs PartyState or calls dataclasses.replace on a party type
  (AST scan of src/karaoke, excluding karaoke/party). The reducer stays the only writer.
- Every `kind` literal in contract.py is unique within its union (pydantic also checks; this gives a readable error).
- web/src/wire/generated.ts is listed in web/.gitignore (it must never be committed and drift).
"""


def test_only_reduce_builds_party_state() -> None:
    raise NotImplementedError


def test_generated_wire_is_not_committed() -> None:
    raise NotImplementedError
