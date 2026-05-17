# Active Pack — Affiliate Feed Pipeline

## Purpose

This local pack describes the feed pipeline used to ingest affiliate product offers and connect them to the perfume catalog.

## Scope

- advertiser feed discovery;
- feed download;
- raw staging;
- normalization;
- perfume-specific parsing;
- product and variant matching;
- offer upsert;
- product candidate generation;
- reporting;
- operational safety.

## First target

Awin / Perfumerias Comas FR.

## Design rule

The pipeline must be generic enough to support future advertisers and networks.

Comas-specific behavior belongs in configuration, fixtures, or tests, not hard-coded business logic.
