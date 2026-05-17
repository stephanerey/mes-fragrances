# Secrets Strategy

## Rule

No secret may be committed to Git.

This includes:

- Awin API token;
- Awin product feed API key;
- database password;
- signed feed download URLs;
- production `.env` files;
- production database dumps;
- private SSH keys.

## Worker environment file

Recommended production path:

```text
/opt/mes-fragrances/affiliate-worker/.env
```

Recommended ownership and permissions:

```bash
chown <deployment-user>:<deployment-group> /opt/mes-fragrances/affiliate-worker/.env
chmod 600 /opt/mes-fragrances/affiliate-worker/.env
```

Adapt the path after filling `00_environment/vps_inventory.md`.

## Template file

The repository should contain only:

```text
affiliate-worker/.env.example
```

This file must contain keys and safe placeholder values only.

## Expected variables

```env
DATABASE_URL=postgresql://user:password@db:5432/mes_fragrances
AFFILIATE_IMPORT_MODE=production
AFFILIATE_LOG_LEVEL=INFO
AFFILIATE_DATA_DIR=/data
AFFILIATE_DEACTIVATE_AFTER_MISSED_IMPORTS=3
AFFILIATE_MATCH_AUTO_THRESHOLD=95
AFFILIATE_MATCH_REVIEW_THRESHOLD=85
AWIN_PUBLISHER_ID=
AWIN_API_TOKEN=
AWIN_PRODUCT_FEED_API_KEY=
```

## Docker Compose

Use `env_file` or Docker secrets.

Initial acceptable pattern:

```yaml
services:
  affiliate-worker:
    env_file:
      - ./affiliate-worker/.env
```

Do not expose secrets through command-line arguments.

## Logs and reports

Logs and reports must never include:

- full `DATABASE_URL`;
- API tokens;
- feed API keys;
- signed download URLs;
- raw request headers containing authorization.

Configuration display commands may show boolean flags such as:

```json
{
  "database_url_configured": true,
  "awin_api_token_configured": true
}
```

but must not show the values.

## Rotation

If a secret is accidentally committed or logged:

1. remove the secret from Git/logs if possible;
2. rotate it immediately in the source system;
3. update the VPS `.env`;
4. document the incident in the PR or operations notes without repeating the secret.
