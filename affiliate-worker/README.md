# Affiliate Worker

Python batch worker for Mes Fragrances affiliate feed processing.

This worker is intentionally separate from the CIS container.

## Commands

From this directory:

```bash
python -m app.main --help
python -m app.main show-config
python -m app.main inspect-db
python -m app.main migrate-db
python -m app.main import-local-csv --advertiser 105475 --feed-id 97867 --path /data/feeds/comas.csv --dry-run
```

## Database migration workflow

Before production migrations, inspect the schema:

```bash
python -m app.main inspect-db
```

Apply safe isolated affiliate migrations:

```bash
python -m app.main migrate-db
```

Template migrations, such as `product_variants`, are skipped by default because they depend on the actual CIS product table name.

Only apply templates after schema confirmation:

```bash
python -m app.main migrate-db --include-templates
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
