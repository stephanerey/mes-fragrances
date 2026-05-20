# Codex Task PR01 — Worker Docker Skeleton

## Goal

Create the initial standalone affiliate worker project.

## Branch

```text
feat/affiliate-worker-skeleton
```

## Scope

Implement only:

- `affiliate-worker/` Python project skeleton;
- Dockerfile;
- `.dockerignore`;
- `.env.example`;
- CLI entry point;
- configuration loading;
- logging setup;
- README with local and Docker commands;
- minimal tests.

## Out of scope

Do not implement:

- database migrations;
- database connections;
- CSV parsing;
- Awin live API access;
- offer upsert;
- matching;
- CIS front-end integration;
- cron/systemd deployment.

## Expected file layout

```text
affiliate-worker/
    pyproject.toml
    Dockerfile
    .dockerignore
    .env.example
    README.md
    app/
        __init__.py
        main.py
        config.py
        logging_config.py
    tests/
        test_cli.py
        test_config.py
```

## CLI requirements

The CLI must support:

```bash
python -m app.main --help
python -m app.main show-config
python -m app.main import-local-csv --advertiser 105475 --feed-id 97867 --path /data/feeds/comas.csv --dry-run
python -m app.main import-feeds --network awin --dry-run
```

For PR01, import commands may be placeholders, but they must:

- parse arguments;
- return a clear message;
- not contact Awin;
- not write to DB.

## Configuration requirements

Load settings from environment variables:

```text
DATABASE_URL
AFFILIATE_IMPORT_MODE
AFFILIATE_LOG_LEVEL
AFFILIATE_DATA_DIR
AFFILIATE_DEACTIVATE_AFTER_MISSED_IMPORTS
AFFILIATE_MATCH_AUTO_THRESHOLD
AFFILIATE_MATCH_REVIEW_THRESHOLD
AWIN_PUBLISHER_ID
AWIN_API_TOKEN
AWIN_PRODUCT_FEED_API_KEY
```

`show-config` must not print secret values.

It may print whether secrets are configured.

## Docker requirements

The Docker image must:

- use Python 3.12;
- expose no ports;
- create `/data/feeds`, `/data/reports`, `/data/logs`;
- run `python -m app.main` as entry point or default command.

## Validation commands

From `affiliate-worker/`:

```bash
pip install -e .[dev]
python -m app.main --help
python -m app.main show-config
pytest
ruff check .
```

From repo root:

```bash
docker build -t mes-fragrances-affiliate-worker ./affiliate-worker
docker run --rm mes-fragrances-affiliate-worker --help
```

## Acceptance criteria

- container builds;
- `python -m app.main --help` works;
- `show-config` does not print secrets;
- placeholder commands are explicit and safe;
- no public ports are exposed;
- no secrets are committed;
- PR remains limited to worker skeleton.

## PR description must include

- summary of files added;
- validation commands run;
- explicit note that DB/Awin/import logic is not implemented yet;
- next recommended task: PR02 Awin feed discovery and download smoke test.