# System Architecture — Affiliate System

## Target architecture

```text
Awin / future affiliate networks
        |
        v
affiliate-worker Docker container
        |
        +--> feed discovery
        +--> feed download
        +--> raw staging
        +--> normalization
        +--> matching
        +--> offers upsert
        +--> candidates creation
        +--> reports/logs
        |
        v
CIS database
        |
        v
CIS front-end and admin
```

## Container model

The worker must be a separate Docker service:

```text
cis                 existing CMS container(s)
db                  existing database service
caddy               existing reverse proxy if separate
affiliate-worker    new batch worker, no public port
```

## Worker execution model

V1 should support execution as a batch command:

```bash
docker compose run --rm affiliate-worker python -m app.main import-feeds
```

The command is launched by Ubuntu cron or systemd timer.

## Why not inside CIS

The worker must not run inside the CIS container because it has different operational constraints:

- long-running batch work;
- external feed downloads;
- large CSV parsing;
- bulk database writes;
- separate failure mode;
- separate secrets;
- independent deployment cadence.

If the worker fails, the website must continue serving existing offers.

## Internal network

The worker must join the Docker internal network that can reach the database.

It must not publish ports.

Expected Compose pattern:

```yaml
services:
  affiliate-worker:
    build: ./affiliate-worker
    env_file:
      - ./affiliate-worker/.env
    volumes:
      - ./affiliate-worker/data:/data
    networks:
      - internal
    depends_on:
      - db
    restart: "no"
```

The actual service names must be adapted after inspecting the CIS Docker Compose stack.

## Source layout proposal

```text
affiliate-worker/
    pyproject.toml
    Dockerfile
    .env.example
    app/
        main.py
        config.py
        logging_config.py
        db/
            session.py
            models.py
            repositories.py
        networks/
            base.py
            awin/
                client.py
                feed_list.py
                feed_downloader.py
                parser.py
        normalization/
            text.py
            perfume.py
            price.py
        matching/
            matcher.py
            scoring.py
            rules.py
        import_pipeline/
            runner.py
            staging.py
            offers_upsert.py
            candidates.py
        reports/
            import_report.py
```

## Network abstraction

Code should define a generic interface for affiliate networks.

Awin is the first implementation, not the only supported design.

Expected conceptual interface:

```python
class AffiliateNetworkClient:
    def list_feeds(self): ...
    def download_feed(self, feed): ...
    def get_program_details(self, advertiser_id: str): ...
```

## Data flow

```text
feed list -> feed download -> checksum -> import_run -> raw rows -> normalized rows -> matching -> offers/candidates -> report
```

## Error handling

A failed feed import must:

- mark the import run as failed;
- log the error;
- keep previous active offers untouched unless the failure happens after a safe transaction boundary;
- allow retry on next execution.

## Dry-run mode

The worker should support a dry-run mode that parses and reports without mutating offer/candidate tables.

## Future extensions

The architecture must allow:

- additional Awin advertisers;
- future affiliate networks;
- click tracking;
- Awin transaction import;
- advertiser performance scoring;
- admin review UI for candidates.