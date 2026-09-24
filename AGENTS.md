# Ketoshop agent guide

Ketoshop is a Telegram marketplace bot and Mini App. The root `README.md`
contains old SQLite/Railway setup examples. Current code uses PostgreSQL via
`asyncpg` in `database.py`; production deploys from `master` through
`.github/workflows/{ci,deploy}.yml` to netcup. Production bot transport is
polling, so do not start a second process with its live token.

## Working style

- Understand the request, repository guidance and relevant code before editing.
  Ask one focused question if a material product decision is unclear; otherwise
  state the assumption.
- Prefer the simplest change that meets the task; avoid unrelated refactors and
  dependencies.
- Keep edits within the requested behavior and preserve existing business,
  safety and release rules.
- Run relevant checks and report what changed, what passed, and anything that
  could not be verified.

## Checks and boundaries

- The bot, Mini App server and scheduled jobs share one process. A startup
  failure affects ordering, customer messages and background work together.
- For a focused change, run the relevant `unittest` file and the full CI
  commands before a PR: `python -m compileall -q .`, the import smoke test in
  `.github/workflows/ci.yml`, and `python -m unittest discover -s tests -v`.
- Existing CI covers syntax, imports and a few regression cases. It does not
  establish that all customer checkout and admin paths work; add targeted
  behavior checks when changing those paths.

## Delivery

- Make one task one branch/PR, with the changed user behavior and checks stated.
- No test may send real orders, broadcasts, payment requests or Meta events.
- Prices, payment, admin access, order state, database migrations, scheduled
  customer sends, secrets and deploy settings need owner review.
- Verify the running image SHA and health after release. Do not call a green
  workflow a deploy if its SSH step was skipped.
