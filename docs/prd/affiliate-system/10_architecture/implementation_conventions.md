# Implementation Conventions

## Repository policy

`stephanerey/mes-fragrances` is the canonical implementation repository for the affiliate system.

Codex must add implementation files here.

## Language and runtime

Use:

- Python `3.12` for the affiliate worker;
- Docker for production execution;
- Docker Compose integration after inspecting the CIS stack;
- PostgreSQL assumptions only after confirming the CIS database engine.

If the live CIS database is not PostgreSQL, stop and update the PRD before implementing migrations.

## Python packaging

For the first implementation, prefer a simple, explicit Python project:

```text
affiliate-worker/
    pyproject.toml
    Dockerfile
    .env.example
    app/
    tests/
```

Do not introduce Poetry unless there is a strong reason.

`pip install -e .[dev]` should be sufficient for local development.

## Recommended dependencies

Initial recommended dependencies:

```text
psycopg[binary]      PostgreSQL access
pydantic-settings    optional config validation
python-dotenv        optional local env loading
rapidfuzz            fuzzy matching, from PR5 onward
pytest               tests
ruff                 linting
```

Keep dependencies minimal. Do not add heavy frameworks unless needed.

## Database access

For early PRs, prefer:

- SQL files for migrations;
- psycopg3 for database access;
- repository/helper modules for DB queries.

SQLAlchemy may be introduced later only if it reduces complexity.

Do not add Alembic until there is a clear migration workflow need. If Alembic is introduced, document the reason in the PR.

## CLI conventions

The worker must expose a command line interface through:

```bash
python -m app.main <command>
```

Expected early commands:

```bash
python -m app.main --help
python -m app.main show-config
python -m app.main inspect-db
python -m app.main migrate-db
python -m app.main import-local-csv --advertiser 105475 --feed-id 97867 --path /data/feeds/comas.csv --dry-run
```

## Docker conventions

The worker container:

- must not expose `ports:`;
- must use `/data` for feeds, reports and logs;
- must read runtime config from `.env` or Docker secrets;
- must be runnable with `docker compose run --rm affiliate-worker ...`.

## Code style

Use:

```bash
ruff check .
pytest
```

from `affiliate-worker/` once the worker exists.

## Testing conventions

Each implementation PR should include tests for the new behavior.

Use small fixtures, not the full Comas feed.

The full feed can be used manually on the VPS, but should not be committed to Git.

## Reports

Worker commands that process data should write JSON reports under:

```text
/data/reports/
```

Reports must not contain secrets.

## Error handling

Batch commands should:

- fail with a non-zero exit code on error;
- log a clear error;
- preserve previous valid state;
- be safe to retry.

## PRD update rule

If implementation choices differ from this file, update this PRD in the same PR or document the reason in the PR description.
