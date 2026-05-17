# Affiliate Worker

Python batch worker for Mes Fragrances affiliate feed processing.

This is PR1 skeleton only. It intentionally does not implement database migrations, CSV parsing, offer upsert, or Awin live API calls yet.

## Commands

From this directory:

```bash
python -m app.main --help
python -m app.main show-config
python -m app.main import-local-csv --advertiser 105475 --feed-id 97867 --path /data/feeds/comas.csv --dry-run
```

## Docker build

```bash
docker build -t mes-fragrances-affiliate-worker ./affiliate-worker
```

## Docker run

```bash
docker run --rm mes-fragrances-affiliate-worker --help
```

With local data volume:

```bash
docker run --rm \
  --env-file affiliate-worker/.env \
  -v "$(pwd)/affiliate-worker/data:/data" \
  mes-fragrances-affiliate-worker show-config
```

## Compose example

See `docker-compose.affiliate-worker.example.yml` at repository root.

## Environment

Copy `.env.example` to `.env` on the VPS and fill real values there.

Do not commit `.env`.

## PRD

Read `docs/prd/affiliate-system/START_HERE.md` before changing worker behavior.
