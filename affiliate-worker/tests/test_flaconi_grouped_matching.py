from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from app.config import Settings
from app.flaconi_grouped_matching import (
    FlaconiGroupedMatchingService,
    GroupCandidate,
    GroupedOffer,
    GroupedSourceRow,
    _best_catalog_candidates,
    _build_catalog_indexes,
    _classify_group,
    _group_id,
    _group_key,
)
from app.matching import CatalogPerfume, build_perfume_match_key


def make_settings(tmp_path: Path) -> Settings:
    return Settings.model_validate(
        {
            "AFFILIATE_DATA_DIR": str(tmp_path / "data"),
            "DATABASE_URL": "postgresql://user:pass@localhost/test",
        }
    )


def make_row(
    *,
    product_id: str,
    brand: str,
    name: str,
    concentration: str | None,
    volume_ml: Decimal | None,
    price: str,
    external_id: str,
) -> GroupedSourceRow:
    normalized_brand = brand.lower().replace("&", "and").replace(".", "")
    normalized_brand = " ".join(normalized_brand.split())
    alias_brand = {
        "rabanne": "paco rabanne",
        "dolce & gabbana": "dolce and gabbana",
    }.get(normalized_brand, normalized_brand)
    return GroupedSourceRow(
        flaconi_product_id=product_id,
        merchant_product_id=f"merchant-{product_id}",
        brand=brand,
        normalized_brand=normalized_brand,
        alias_brand=alias_brand,
        source_name=name,
        normalized_name=build_perfume_match_key(
            name,
            brand=brand,
            concentration=concentration,
            volume_ml=volume_ml,
        ),
        concentration=concentration,
        volume_ml=volume_ml,
        price=Decimal(price),
        currency="EUR",
        affiliate_url=f"https://example.test/{product_id}",
        image_url="https://example.test/image.jpg",
        category="Fragrance",
        merchant_category="Fragrance",
        product_type="Perfume",
        description=None,
        identifiers={"ean": external_id, "gtin": external_id, "upc": "", "mpn": ""},
        is_fragrance=True,
        exclusion_reasons=[],
        raw_payload={},
    )


def make_perfume(
    *,
    perfume_id: str,
    brand: str,
    name: str,
    concentration: str | None = None,
    volume_ml: Decimal | None = None,
    ean: str | None = None,
) -> CatalogPerfume:
    return CatalogPerfume(
        id=perfume_id,
        name=name,
        slug=None,
        brand=brand,
        normalized_brand=brand.lower().replace("&", "and"),
        match_key=build_perfume_match_key(
            name,
            brand=brand,
            concentration=concentration,
            volume_ml=volume_ml,
        ),
        slug_key="",
        concentration=concentration,
        volume_ml=volume_ml,
        identifiers={"ean": ean or "", "gtin": ean or "", "upc": "", "mpn": ""},
    )


def test_duplicate_same_product_rows_share_group_key() -> None:
    first = make_row(
        product_id="1",
        brand="Rabanne",
        name="Rabanne 1 Million Eau de parfum",
        concentration="edp",
        volume_ml=None,
        price="79.99",
        external_id="111",
    )
    second = make_row(
        product_id="2",
        brand="Rabanne",
        name="Rabanne 1 Million Eau de parfum",
        concentration="edp",
        volume_ml=None,
        price="89.99",
        external_id="222",
    )
    assert _group_key(first) == _group_key(second)


def test_same_name_different_volumes_stay_in_distinct_groups() -> None:
    first = make_row(
        product_id="1",
        brand="Rabanne",
        name="Rabanne 1 Million Eau de parfum 50 ml",
        concentration="edp",
        volume_ml=Decimal("50"),
        price="69.99",
        external_id="111",
    )
    second = make_row(
        product_id="2",
        brand="Rabanne",
        name="Rabanne 1 Million Eau de parfum 100 ml",
        concentration="edp",
        volume_ml=Decimal("100"),
        price="94.99",
        external_id="222",
    )
    assert _group_key(first) != _group_key(second)


def test_unknown_volume_multi_row_group_is_not_promoted_to_strong() -> None:
    rows = [
        make_row(
            product_id="1",
            brand="Tom Ford",
            name="Tom Ford Signature Black Orchid Eau de parfum",
            concentration="edp",
            volume_ml=None,
            price="80.00",
            external_id="111",
        ),
        make_row(
            product_id="2",
            brand="Tom Ford",
            name="Tom Ford Signature Black Orchid Eau de parfum",
            concentration="edp",
            volume_ml=None,
            price="95.00",
            external_id="222",
        ),
    ]
    perfume = make_perfume(
        perfume_id="perf-1",
        brand="Tom Ford",
        name="Signature Black Orchid",
        concentration="edp",
        volume_ml=Decimal("100"),
    )
    candidates = [
        GroupCandidate(
            perfume=perfume,
            score=0.96,
            method="brand_name_similarity",
            risk_flags=(),
        )
    ]
    classification, _, _, _ = _classify_group(
        rows,
        candidates=candidates,
        offer_state={},
    )
    assert classification == "GROUP_BLOCKED_VOLUME_UNKNOWN"


def test_brand_alias_can_recover_rabanne_existing_match() -> None:
    row = make_row(
        product_id="1",
        brand="Rabanne",
        name="Rabanne 1 Million Eau de parfum 100 ml",
        concentration="edp",
        volume_ml=Decimal("100"),
        price="99.00",
        external_id="",
    )
    perfume = make_perfume(
        perfume_id="perf-1",
        brand="Paco Rabanne",
        name="1 Million",
        concentration="edp",
        volume_ml=Decimal("100"),
    )
    by_brand, by_identifier = _build_catalog_indexes([perfume])
    candidates = _best_catalog_candidates(
        row,
        catalog_by_brand=by_brand,
        catalog_by_identifier=by_identifier,
    )
    assert candidates
    assert candidates[0].perfume.id == "perf-1"
    assert candidates[0].score >= 0.92


def test_boucheron_jaipure_stays_blocked_variant_conflict() -> None:
    row = make_row(
        product_id="1",
        brand="Boucheron",
        name="Boucheron Jaipure Homme Eau de parfum 100 ml",
        concentration="edp",
        volume_ml=Decimal("100"),
        price="72.00",
        external_id="",
    )
    perfume = make_perfume(
        perfume_id="perf-1",
        brand="Boucheron",
        name="Boucheron Pour Homme Eau de Parfum",
        concentration="edp",
        volume_ml=Decimal("100"),
    )
    by_brand, by_identifier = _build_catalog_indexes([perfume])
    candidates = _best_catalog_candidates(
        row,
        catalog_by_brand=by_brand,
        catalog_by_identifier=by_identifier,
    )
    classification, risk_flags, _, _ = _classify_group(
        [row],
        candidates=candidates,
        offer_state={},
    )
    assert "known_false_positive_boucheron_jaipure" in risk_flags
    assert classification == "GROUP_BLOCKED_VARIANT_CONFLICT"


def test_phase1_ready_excludes_dolce_and_gabbana(tmp_path: Path) -> None:
    service = FlaconiGroupedMatchingService(make_settings(tmp_path))
    d_and_g_row = make_row(
        product_id="1",
        brand="Dolce & Gabbana",
        name="Dolce & Gabbana Light Blue Eau de parfum 50 ml",
        concentration="edp",
        volume_ml=Decimal("50"),
        price="65.00",
        external_id="111",
    )
    safe_row = make_row(
        product_id="2",
        brand="Rabanne",
        name="Rabanne Phantom Eau de parfum 100 ml",
        concentration="edp",
        volume_ml=Decimal("100"),
        price="79.00",
        external_id="222",
    )
    d_and_g_perfume = make_perfume(
        perfume_id="perf-dg",
        brand="Dolce & Gabbana",
        name="Light Blue",
        concentration="edp",
        volume_ml=Decimal("50"),
    )
    safe_perfume = make_perfume(
        perfume_id="perf-rabanne",
        brand="Paco Rabanne",
        name="Phantom",
        concentration="edp",
        volume_ml=Decimal("100"),
    )
    groups = [
        GroupedOffer(
            group_id=_group_id(_group_key(d_and_g_row)),
            group_key=_group_key(d_and_g_row),
            rows=(d_and_g_row,),
            representative=d_and_g_row,
            classification="EXISTING_GROUP_STRONG_TO_CREATE_OFFER",
            volume_detection_status="known_single",
            risk_flags=(),
            best_match=GroupCandidate(d_and_g_perfume, 0.99, "brand_name_similarity", ()),
            second_match=None,
        ),
        GroupedOffer(
            group_id=_group_id(_group_key(safe_row)),
            group_key=_group_key(safe_row),
            rows=(safe_row,),
            representative=safe_row,
            classification="EXISTING_GROUP_STRONG_TO_CREATE_OFFER",
            volume_detection_status="known_single",
            risk_flags=(),
            best_match=GroupCandidate(safe_perfume, 0.99, "brand_name_similarity", ()),
            second_match=None,
        ),
    ]
    rows = service._phase1_ready_rows(groups, offer_state={})
    assert len(rows) == 1
    assert rows[0]["matched_perfume_id"] == "perf-rabanne"
