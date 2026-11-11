# Karaoke app v2

A ground-up rebuild of a home karaoke app. The user searches for a song, the app prepares a sing-along track with synced lyrics, guests queue songs from their phones, and the host screen plays them in turn.

## Work spec-first

1. The spec in `docs/spec/` is the source of truth. Write no application code until the user approves the spec.
2. When the user gives a requirement, record it in the spec in the user's terms. Mark anything you inferred as `Assumption:` so the user can confirm or reject it.
3. Keep open questions in the spec's open-questions section, not only in chat.
4. When code and spec disagree, stop and ask which one is wrong. Fix the spec first, then the code.

## Treat v1 as a lesson, not a source

An earlier version exists outside this repo. Do not copy its code, import its modules, read its data folders, or link to its path. Its known failures are recorded in `docs/spec/00-product.md` so v2 designs them out:

- Fragile YouTube integration that broke whenever YouTube changed.
- Tangled code with UI, playback, downloading, and processing mixed together.
- A confusing user experience.

## Use pstack for non-trivial work

- Start each non-trivial task with `/pstack:poteto-mode`. Pass a goal and a check that can pass or fail.
- Model choices per role live in `~/.claude/rules/pstack-models.md`. Change them with `/pstack:setup-pstack`.
- Write docs and specs under `/pstack:technical-writing`.
- Once the app runs, generate a verification skill with `/pstack:create-verification-skill` so agents can prove changes in the real app.

## Repository layout

- `docs/spec/` holds the product and technical spec. `docs/spec/README.md` lists the files and their status.
- The tech stack is not chosen yet. The spec decides it.
