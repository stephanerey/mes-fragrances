# Awin Integration Notes

## Purpose

Awin is the first affiliate network to support.

The implementation must not make Awin the global domain model.

## First advertiser

```text
name: Perfumerias Comas FR
network: awin
network_advertiser_id: 105475
network_feed_id: 97867
locale: fr_FR
currency: EUR
```

## Expected implementation phases

### Phase 1 — Local CSV

Support importing the provided Comas CSV from disk.

This allows deterministic parsing, tests, and database pipeline validation.

### Phase 2 — Product feed discovery

Use Awin feed discovery/listing to identify available feeds and remote update dates.

Skip downloads when the feed has not changed.

### Phase 3 — Product feed download

Download selected feeds automatically using environment-provided credentials.

### Phase 4 — Program and performance enrichment

Later enrich advertisers with:

- commission range;
- membership status;
- EPC;
- conversion rate;
- validation metrics.

## Required safety

- no Awin secrets in Git;
- no secrets in logs;
- no API URLs with keys printed to reports;
- robust handling of unavailable feeds;
- clear failed import status.

## Configuration-first approach

Advertiser IDs, feed IDs, locales and category filters must be configurable.