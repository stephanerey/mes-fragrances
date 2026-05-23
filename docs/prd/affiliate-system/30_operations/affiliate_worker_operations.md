# Affiliate Worker Operations

## Production recommendation

Recommended scheduler on the OVH Ubuntu VPS:

- host `systemd` service + timer;
- `docker run --rm` against `mes-fragrances_cis_default`;
- worker state written only under `/home/eva/mes-fragrances/affiliate-worker-data`.

This PR does not enable the timer automatically.

## Daily commands

Manual dry-run from the repository root:

```bash
docker run --rm \
  --network mes-fragrances_cis_default \
  --env-file ./affiliate-worker/.env \
  -v "$(pwd)/affiliate-worker-data:/data" \
  mes-fragrances-affiliate-worker run-affiliate-pipeline --network awin --dry-run
```

Manual non-dry-run:

```bash
docker run --rm \
  --network mes-fragrances_cis_default \
  --env-file ./affiliate-worker/.env \
  -v "$(pwd)/affiliate-worker-data:/data" \
  mes-fragrances-affiliate-worker run-affiliate-pipeline --network awin
```

Single-feed dry-run:

```bash
docker run --rm \
  --network mes-fragrances_cis_default \
  --env-file ./affiliate-worker/.env \
  -v "$(pwd)/affiliate-worker-data:/data" \
  mes-fragrances-affiliate-worker run-affiliate-pipeline \
    --network awin \
    --advertiser 105475 \
    --feed-id 97867 \
    --dry-run
```

Optional random startup delay:

```bash
docker run --rm \
  --network mes-fragrances_cis_default \
  --env-file ./affiliate-worker/.env \
  -v "$(pwd)/affiliate-worker-data:/data" \
  mes-fragrances-affiliate-worker run-affiliate-pipeline \
    --network awin \
    --random-delay-max-seconds 300
```

## Reports

Aggregate pipeline reports are written under:

```text
/home/eva/mes-fragrances/affiliate-worker-data/reports/
```

Naming:

```text
affiliate_pipeline_YYYYMMDD_HHMMSS_<network>.json
latest_affiliate_pipeline_report.json
```

The latest file is a copied JSON file for easy inspection on the host and in the
Docker bind mount.

Inspect the latest report:

```bash
cat /home/eva/mes-fragrances/affiliate-worker-data/reports/latest_affiliate_pipeline_report.json
```

## Locking

The orchestration command uses a PostgreSQL advisory lock.

Behavior:

- if the lock is acquired, the run proceeds;
- if the lock is already held, the worker exits with `status=skipped_locked`;
- no partial pipeline starts when the lock is unavailable.

Because the lock is tied to the PostgreSQL session, abnormal process exit does
not leave a permanent stale lock.

## Failure behavior

On failure:

- the command exits non-zero;
- a failure report is still written;
- downstream steps for the failed feed are skipped;
- failed feeds do not trigger stale-offer deactivation;
- previous offers and website state remain intact.

The current raw staging model is deduplicated across runs. Because of that, the
pipeline disables stale-offer updates automatically whenever the current raw
import is not a fully materialized snapshot of the live feed. This keeps the
daily scheduler conservative until snapshot-aware stale logic is implemented.

## Logs

Recommended production logging strategy:

- rely on `journald` for the host `systemd` unit output;
- keep JSON reports under `/data/reports`;
- do not persist full downloaded feed payloads by default;
- do not print secrets, signed feed URLs, or full `DATABASE_URL` values.

Inspect recent logs:

```bash
journalctl -u mes-fragrances-affiliate-worker.service -n 100 --no-pager
```

Follow live logs:

```bash
journalctl -u mes-fragrances-affiliate-worker.service -f
```

## Systemd deployment

Templates committed in this repository:

- `affiliate-worker/deploy/systemd/mes-fragrances-affiliate-worker.service`
- `affiliate-worker/deploy/systemd/mes-fragrances-affiliate-worker.timer`

Suggested installation:

```bash
sudo cp affiliate-worker/deploy/systemd/mes-fragrances-affiliate-worker.service /etc/systemd/system/
sudo cp affiliate-worker/deploy/systemd/mes-fragrances-affiliate-worker.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mes-fragrances-affiliate-worker.timer
```

Check timer state:

```bash
systemctl status mes-fragrances-affiliate-worker.timer
systemctl list-timers mes-fragrances-affiliate-worker.timer
```

Disable the timer:

```bash
sudo systemctl disable --now mes-fragrances-affiliate-worker.timer
```

Run the service immediately:

```bash
sudo systemctl start mes-fragrances-affiliate-worker.service
```

## Cron alternative

`systemd` is the recommended scheduler on this VPS because it gives persistent
timers, journald logs, and host-level randomized delay. If needed, a simple
cron alternative is:

```cron
20 4 * * * cd /home/eva/mes-fragrances && docker run --rm --network mes-fragrances_cis_default --env-file ./affiliate-worker/.env -v "$(pwd)/affiliate-worker-data:/data" mes-fragrances-affiliate-worker run-affiliate-pipeline --network awin
```

## Validation checks

Useful SQL checks after a non-dry-run pipeline:

```bash
docker exec mes-fragrances_cis-db-1 \
  psql -U pilot -d pilot -c "
  select count(*) as raw_feed_items from raw_feed_items;
  select count(*) as normalized_feed_items from normalized_feed_items;
  select count(*) as offers from offers;
  select count(*) as candidates from product_match_candidates;
  select count(*) as mappings from external_product_mappings;
  select count(*) as cis_perfume_offers from perfume_offers;
  "
```

The worker must not write to:

- `perfumes`
- `perfume_offers`
- `external_product_mappings`

## Retention

Initial retention policy for PR09:

- keep JSON reports indefinitely;
- keep `latest_affiliate_pipeline_report.json` overwritten on each run;
- rely on journald and host Docker logging policy for log rotation;
- do not persist full downloaded feed payloads unless later operations require it.
