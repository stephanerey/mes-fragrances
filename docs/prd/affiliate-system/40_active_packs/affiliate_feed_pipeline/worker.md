# Worker Pack Notes

## Runtime

The worker is a Dockerized Python batch process.

It is launched manually, by cron, or by systemd timer.

## First implementation command

```bash
docker compose run --rm affiliate-worker python -m app.main import-local-csv --advertiser 105475 --feed-id 97867 --path /data/feeds/comas.csv
```

## Required modes

- normal import;
- dry-run;
- local CSV import;
- future Awin API/feed import.

## Output

The worker must write:

- database import run;
- structured logs;
- JSON report.

## Failure

The worker must fail loudly but safely.

No failed import should corrupt existing active offers.
