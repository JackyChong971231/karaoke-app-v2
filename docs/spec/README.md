# Karaoke app v2 spec

This folder is the source of truth for what v2 does and how it is built. No application code is written until the user approves the product spec and the technical spec.

| File | Covers | Status |
| --- | --- | --- |
| [00-product.md](00-product.md) | Who uses the app, what they can do, and what good looks like | Approved 2026-11-11. Amendments approved 2026-11-12. |
| [01-technical.md](01-technical.md) | Stack, architecture, data model, and external integrations | Approved 2026-11-11. Changes for 2026-11-12 await approval. |

## How a requirement becomes spec

1. The user states a requirement in chat.
2. The agent records it in the right file, in the user's terms.
3. Anything the agent inferred is marked `Assumption:` until the user confirms it.
4. Unresolved items go to the file's open-questions section.
5. The user approves a file by saying so in chat. The agent then sets its status to `Approved` in the table above.
