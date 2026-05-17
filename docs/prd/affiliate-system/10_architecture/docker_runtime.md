# Docker Runtime Strategy

## Recommended V1 runtime

Use a separate batch container launched by the Ubuntu host scheduler.

```text
Ubuntu cron/systemd timer
        |
        v
docker compose run --rm affiliate-worker python -m app.main import-feeds
```

## Why host scheduler first

This is simpler than an internal scheduler container because:

- no permanent process is required;
- resource usage is limited to import windows;
- logs are easier to reason about at first;
- retries can be handled by the next scheduled execution;
- double scheduling risk is lower.

## Later option

A permanent scheduler service may be introduced later if many recurring jobs are needed.

Example future command:

```yaml
affiliate-worker:
  command: python -m app.scheduler
  restart: unless-stopped
```

This is not required for V1.

## Required environment variables

Expected variables:

```env
DATABASE_URL=
AWIN_PUBLISHER_ID=
AWIN_API_TOKEN=
AWIN_PRODUCT_FEED_API_KEY=
AFFILIATE_IMPORT_MODE=production
AFFILIATE_LOG_LEVEL=INFO
AFFILIATE_DEACTIVATE_AFTER_MISSED_IMPORTS=3
AFFILIATE_MATCH_AUTO_THRESHOLD=95
AFFILIATE_MATCH_REVIEW_THRESHOLD=85
```

The exact Awin credential names may be adapted during implementation.

## Volumes

The worker should have a persistent data volume for downloaded feeds and reports:

```text
/data/feeds/
/data/reports/
/data/logs/
```

Recommended host mapping:

```text
./affiliate-worker/data:/data
```

## File retention

Initial retention policy:

- keep compressed raw downloaded feeds for 30 days;
- keep import reports indefinitely until reviewed;
- logs may be rotated by host logrotate or Docker logging config.

## Cron example

Example host cron:

```cron
17 3 * * * cd /opt/mes-fragrances && docker compose run --rm affiliate-worker python -m app.main import-feeds >> /var/log/affiliate-worker.log 2>&1
```

Prefer a random startup delay inside the worker to avoid API bursts:

```python
import random
import time

time.sleep(random.randint(10, 120))
```

## Operational commands

Manual import:

```bash
docker compose run --rm affiliate-worker python -m app.main import-feeds
```

Dry-run import:

```bash
docker compose run --rm affiliate-worker python -m app.main import-feeds --dry-run
```

Import one advertiser:

```bash
docker compose run --rm affiliate-worker python -m app.main import-feeds --advertiser 105475
```

Show latest report:

```bash
ls -lt affiliate-worker/data/reports | head
```

## Safety

The worker container must not contain Caddy configuration and must not expose `ports:`.
