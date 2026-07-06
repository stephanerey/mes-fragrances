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
    _decimal_to_string,
    _dedupe_existing_apply_candidates,
    _group_id,
    _group_key,
    _parse_volume_from_fields,
    _price_to_string,
    _source_row_to_dict,
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


def test_decimal_to_string_preserves_integer_trailing_zeros_for_prices() -> None:
    assert _price_to_string(Decimal("210.00")) == "210.00"
    assert _price_to_string(Decimal("200.00")) == "200.00"
    assert _price_to_string(Decimal("280.00")) == "280.00"
    assert _price_to_string(Decimal("21.00")) == "21.00"
    assert _price_to_string(Decimal("34.90")) == "34.90"
    assert _price_to_string(Decimal("134.40")) == "134.40"
    assert _decimal_to_string(Decimal("100.00")) == "100"


def test_grouped_offer_serialization_keeps_bello_rabelo_price() -> None:
    row = make_row(
        product_id="1",
        brand="Liquides Imaginaires",
        name="Liquides Imaginaires Bello Rabelo Eau de parfum 100 ml",
        concentration="edp",
        volume_ml=Decimal("100"),
        price="210.00",
        external_id="111",
    )
    assert _source_row_to_dict(row)["price"] == "210.00"


def test_parse_volume_from_image_url_when_source_text_has_no_volume() -> None:
    row = {
        "product_name": "Aigner Début Eau de parfum",
        "description": "",
        "merchant_category": "Eau de parfum",
        "product_type": "Eau de parfum",
        "keywords": "",
        "specifications": "",
        "image_url": "https://cdn.flaconi.net/media/catalog/product/a/i/aigner-debut-eau-de-parfum-100-ml-4013670509199_live.jpg?r=1WAWZF&c=fr",
    }
    assert _parse_volume_from_fields(row) == Decimal("100")


def test_parse_volume_from_fields_prefers_source_text_over_image_url() -> None:
    row = {
        "product_name": "Memo Paris Marfa Eau de parfum 10 ml",
        "description": "",
        "merchant_category": "Eau de parfum",
        "product_type": "Eau de parfum",
        "keywords": "",
        "specifications": "",
        "image_url": "https://cdn.flaconi.net/media/catalog/product/m/e/memo-paris-marfa-eau-de-parfum-75-ml-1234567890123_live.jpg",
    }
    assert _parse_volume_from_fields(row) == Decimal("10")


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
    rows, blocked = service._phase1_existing_rows(groups, offer_state={})
    assert len(rows) == 1
    assert blocked == []
    assert rows[0]["matched_perfume_id"] == "perf-rabanne"


def test_duplicate_target_generic_parfum_vs_edp_is_blocked() -> None:
    rows = [
        {
            "group_id": "g-edp",
            "source_name": "Versace Crystal Noir Eau de parfum",
            "source_brand": "Versace",
            "source_concentration": "edp",
            "source_price": "45.16",
            "matched_perfume_id": "perf-1",
            "matched_perfume_brand": "Versace",
            "matched_perfume_name": "Versace Crystal Noir",
            "matched_perfume_concentration": "",
            "matched_perfume_concentration_hint": "",
        },
        {
            "group_id": "g-parfum",
            "source_name": "Versace Crystal Noir Parfum",
            "source_brand": "Versace",
            "source_concentration": "parfum",
            "source_price": "84.29",
            "matched_perfume_id": "perf-1",
            "matched_perfume_brand": "Versace",
            "matched_perfume_name": "Versace Crystal Noir",
            "matched_perfume_concentration": "",
            "matched_perfume_concentration_hint": "",
        },
    ]
    ready, blocked = _dedupe_existing_apply_candidates(rows)
    assert ready == []
    assert len(blocked) == 2
    assert {row["block_reason"] for row in blocked} == {"BLOCKED_AMBIGUOUS_VARIANTS"}


def test_duplicate_target_invictus_generic_parfum_vs_edp_is_blocked() -> None:
    rows = [
        {
            "group_id": "g-edp",
            "source_name": "Invictus Eau de parfum",
            "source_brand": "Paco Rabanne",
            "source_concentration": "edp",
            "source_price": "61.03",
            "matched_perfume_id": "perf-invictus",
            "matched_perfume_brand": "Paco Rabanne",
            "matched_perfume_name": "Invictus",
            "matched_perfume_concentration": "",
            "matched_perfume_concentration_hint": "",
        },
        {
            "group_id": "g-parfum",
            "source_name": "Invictus Parfum",
            "source_brand": "Paco Rabanne",
            "source_concentration": "parfum",
            "source_price": "67.88",
            "matched_perfume_id": "perf-invictus",
            "matched_perfume_brand": "Paco Rabanne",
            "matched_perfume_name": "Invictus",
            "matched_perfume_concentration": "",
            "matched_perfume_concentration_hint": "",
        },
    ]
    ready, blocked = _dedupe_existing_apply_candidates(rows)
    assert ready == []
    assert len(blocked) == 2
    assert {row["block_reason"] for row in blocked} == {"BLOCKED_AMBIGUOUS_VARIANTS"}


def test_duplicate_target_explicit_edp_selects_edp_only() -> None:
    rows = [
        {
            "group_id": "g-edp",
            "source_name": "Azzaro Chrome Eau de parfum",
            "source_brand": "Azzaro",
            "source_concentration": "edp",
            "source_price": "61.03",
            "matched_perfume_id": "perf-1",
            "matched_perfume_brand": "Azzaro",
            "matched_perfume_name": "Azzaro Chrome Eau de Parfum",
            "matched_perfume_concentration": "",
            "matched_perfume_concentration_hint": "edp",
        },
        {
            "group_id": "g-parfum",
            "source_name": "Azzaro Chrome Parfum",
            "source_brand": "Azzaro",
            "source_concentration": "parfum",
            "source_price": "61.66",
            "matched_perfume_id": "perf-1",
            "matched_perfume_brand": "Azzaro",
            "matched_perfume_name": "Azzaro Chrome Eau de Parfum",
            "matched_perfume_concentration": "",
            "matched_perfume_concentration_hint": "edp",
        },
    ]
    ready, blocked = _dedupe_existing_apply_candidates(rows)
    assert len(ready) == 1
    assert ready[0]["group_id"] == "g-edp"
    assert len(blocked) == 1
    assert blocked[0]["group_id"] == "g-parfum"


def test_duplicate_target_explicit_parfum_selects_parfum_only() -> None:
    rows = [
        {
            "group_id": "g-edp",
            "source_name": "Boss Bottled Eau de parfum",
            "source_brand": "Hugo Boss",
            "source_concentration": "edp",
            "source_price": "48.48",
            "matched_perfume_id": "perf-1",
            "matched_perfume_brand": "Hugo Boss",
            "matched_perfume_name": "Boss Bottled Parfum",
            "matched_perfume_concentration": "",
            "matched_perfume_concentration_hint": "parfum",
        },
        {
            "group_id": "g-parfum",
            "source_name": "Boss Bottled Parfum",
            "source_brand": "Hugo Boss",
            "source_concentration": "parfum",
            "source_price": "52.90",
            "matched_perfume_id": "perf-1",
            "matched_perfume_brand": "Hugo Boss",
            "matched_perfume_name": "Boss Bottled Parfum",
            "matched_perfume_concentration": "",
            "matched_perfume_concentration_hint": "parfum",
        },
    ]
    ready, blocked = _dedupe_existing_apply_candidates(rows)
    assert len(ready) == 1
    assert ready[0]["group_id"] == "g-parfum"
    assert len(blocked) == 1
    assert blocked[0]["group_id"] == "g-edp"


def test_non_collision_candidate_is_preserved() -> None:
    rows = [
        {
            "group_id": "g-1",
            "source_name": "Jimmy Choo Man Parfum",
            "source_brand": "Jimmy Choo",
            "source_concentration": "parfum",
            "source_price": "69.00",
            "matched_perfume_id": "perf-1",
            "matched_perfume_brand": "Jimmy Choo",
            "matched_perfume_name": "Jimmy Choo Man",
            "matched_perfume_concentration": "",
            "matched_perfume_concentration_hint": "",
        }
    ]
    ready, blocked = _dedupe_existing_apply_candidates(rows)
    assert len(ready) == 1
    assert blocked == []


def test_duplicate_equivalent_rows_collapse_stably_to_one_candidate() -> None:
    rows = [
        {
            "group_id": "g-a",
            "source_name": "Jimmy Choo Man Parfum",
            "source_brand": "Jimmy Choo",
            "source_concentration": "parfum",
            "source_price": "69.00",
            "matched_perfume_id": "perf-1",
            "matched_perfume_brand": "Jimmy Choo",
            "matched_perfume_name": "Jimmy Choo Man Parfum",
            "matched_perfume_concentration": "parfum",
            "matched_perfume_concentration_hint": "parfum",
        },
        {
            "group_id": "g-b",
            "source_name": "Jimmy Choo Man Parfum",
            "source_brand": "Jimmy Choo",
            "source_concentration": "parfum",
            "source_price": "72.00",
            "matched_perfume_id": "perf-1",
            "matched_perfume_brand": "Jimmy Choo",
            "matched_perfume_name": "Jimmy Choo Man Parfum",
            "matched_perfume_concentration": "parfum",
            "matched_perfume_concentration_hint": "parfum",
        },
    ]
    ready, blocked = _dedupe_existing_apply_candidates(rows)
    assert len(ready) == 1
    assert ready[0]["group_id"] == "g-a"
    assert len(blocked) == 1
    assert blocked[0]["block_reason"] == "BLOCKED_DUPLICATE_TARGET"


def test_final_phase1_ready_rows_are_unique_by_target() -> None:
    rows = [
        {
            "group_id": "g-edp",
            "source_name": "Si Eau de parfum",
            "source_brand": "Giorgio Armani",
            "source_concentration": "edp",
            "source_price": "47.11",
            "matched_perfume_id": "perf-si",
            "matched_perfume_brand": "Giorgio Armani",
            "matched_perfume_name": "Si",
            "matched_perfume_concentration": "",
            "matched_perfume_concentration_hint": "",
        },
        {
            "group_id": "g-parfum",
            "source_name": "Si Parfum",
            "source_brand": "Giorgio Armani",
            "source_concentration": "parfum",
            "source_price": "63.53",
            "matched_perfume_id": "perf-si",
            "matched_perfume_brand": "Giorgio Armani",
            "matched_perfume_name": "Si",
            "matched_perfume_concentration": "",
            "matched_perfume_concentration_hint": "",
        },
        {
            "group_id": "g-safe",
            "source_name": "Jimmy Choo Man Parfum",
            "source_brand": "Jimmy Choo",
            "source_concentration": "parfum",
            "source_price": "69.00",
            "matched_perfume_id": "perf-jc",
            "matched_perfume_brand": "Jimmy Choo",
            "matched_perfume_name": "Jimmy Choo Man",
            "matched_perfume_concentration": "",
            "matched_perfume_concentration_hint": "",
        },
    ]
    ready, blocked = _dedupe_existing_apply_candidates(rows)
    assert len(ready) == 1
    assert ready[0]["matched_perfume_id"] == "perf-jc"
    assert len({row["matched_perfume_id"] for row in ready}) == len(ready)
    assert {row["block_reason"] for row in blocked} == {"BLOCKED_AMBIGUOUS_VARIANTS"}
