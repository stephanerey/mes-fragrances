# Matching Rules

## Goal

Match advertiser feed rows to internal catalog products and variants with high precision.

Incorrect automatic matching is worse than leaving an item as a candidate.

## Matching priority

### Priority 1 — Exact identifier

Use exact identifiers when available:

- EAN;
- GTIN;
- UPC;
- MPN if reliable;
- locked external mapping.

### Priority 2 — Locked manual mapping

If `external_product_mappings.locked = true`, it must override fuzzy matching.

Manual mapping is the trusted correction mechanism.

### Priority 3 — Deterministic variant key

Use structured fields when available:

```text
brand + normalized product name + concentration + volume_ml
```

Example key:

```text
lancome|la vie est belle|edp|50
```

### Priority 4 — Fuzzy candidate matching

Fuzzy matching may be used only after normalization and only with guardrails.

Minimum guardrails:

- brand compatible;
- category compatible;
- concentration compatible when known;
- volume compatible when known;
- exclusion keywords absent unless product variant explicitly supports them.

### Priority 5 — Candidate

If confidence is insufficient, create or update a candidate.

## Suggested fuzzy thresholds

```text
score >= 95      auto-match allowed if guardrails pass
85 <= score < 95 needs_review candidate
score < 85       unmatched candidate or rejection
```

Thresholds must be configurable.

## Normalization rules

Normalize names by:

- decoding HTML entities;
- lowercasing;
- removing accents;
- replacing punctuation with spaces;
- collapsing whitespace;
- removing noise tokens only when safe.

## Concentration parsing

Canonical concentration values should include:

```text
EDP
EDT
Extrait
Parfum
Eau de Cologne
Eau Fraiche
Body Mist
Unknown
```

Common mappings:

```text
eau de parfum -> EDP
edp -> EDP
eau de toilette -> EDT
edt -> EDT
extrait de parfum -> Extrait
parfum -> Parfum
```

## Volume parsing

Detect volumes such as:

```text
30 ml
50ml
100 ML
2 x 50 ml
```

For multi-item sets, do not auto-match to a simple variant unless the candidate is explicitly marked as a set.

## Exclusion keywords

Initial exclusion candidates:

```text
coffret
set
duo
trio
tester
testeur
recharge
refill
gel douche
shower gel
lait corps
body lotion
déodorant
deodorant
diffuseur
bougie
candle
```

Some excluded terms may become supported later, but the V1 system should avoid automatic matching for them.

## Category rule for Comas V1

The initial actionable import should prioritize:

```text
category_name == Fragrance
```

Rows outside this category may be staged but should not produce public offers in V1.

## Candidate deduplication

Candidate uniqueness should consider:

- advertiser id;
- network product id;
- merchant product id;
- normalized candidate name;
- candidate volume;
- candidate concentration;
- candidate brand if known.

## Confidence explanation

Every candidate should include a short reason explaining why it was or was not matched.

Examples:

```text
brand matched, name score 91, volume missing: needs review
category not fragrance: rejected_not_perfume
matched by locked external mapping
matched by exact GTIN
```