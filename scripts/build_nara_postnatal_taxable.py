#!/usr/bin/env python3
"""Build the Nara taxable-household postnatal-care research tables.

The optional UI JSON input is an ephemeral export from the public Birth Navi
facility-page form after selecting Nara Prefecture, a resident municipality,
and household type 1 (resident-taxable household).  The committed source CSVs
retain the displayed text.  Derived tables add conservative fee normalization,
provider location, coordinates, and source-versus-display discrepancy flags.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path


COLLECTOR_VERSION = "nara-ui-1.0.0"
PREFECTURE_CODE = "29"
PREFECTURE_NAME = "奈良県"
HOUSEHOLD_TYPE_CODE = "1"
HOUSEHOLD_TYPE_NAME = "住民税課税世帯"

SERVICE_CODES = {
    "短期入所（ショートステイ）型": "1",
    "通所（デイサービス）型（個別）": "2",
    "通所（デイサービス）型（集団）": "3",
    "居宅訪問（アウトリーチ）型": "4",
}

NARA_MUNICIPALITIES = [
    ("29201", "奈良市"), ("29202", "大和高田市"),
    ("29203", "大和郡山市"), ("29204", "天理市"),
    ("29205", "橿原市"), ("29206", "桜井市"),
    ("29207", "五條市"), ("29208", "御所市"),
    ("29209", "生駒市"), ("29210", "香芝市"),
    ("29211", "葛城市"), ("29212", "宇陀市"),
    ("29322", "山添村"), ("29342", "平群町"),
    ("29343", "三郷町"), ("29344", "斑鳩町"),
    ("29345", "安堵町"), ("29361", "川西町"),
    ("29362", "三宅町"), ("29363", "田原本町"),
    ("29385", "曽爾村"), ("29386", "御杖村"),
    ("29401", "高取町"), ("29402", "明日香村"),
    ("29424", "上牧町"), ("29425", "王寺町"),
    ("29426", "広陵町"), ("29427", "河合町"),
    ("29441", "吉野町"), ("29442", "大淀町"),
    ("29443", "下市町"), ("29444", "黒滝村"),
    ("29446", "天川村"), ("29447", "野迫川村"),
    ("29449", "十津川村"), ("29450", "下北山村"),
    ("29451", "上北山村"), ("29452", "川上村"),
    ("29453", "東吉野村"),
]

RELATION_FIELDS = [
    "provider_id", "birth_navi_id", "listing_role",
    "resident_prefecture_code", "resident_prefecture_name",
    "resident_municipality_code", "resident_municipality_name",
    "household_type_code", "household_type", "facility_name_displayed",
    "eligibility_text", "overall_remarks", "observed_service_count",
    "detail_status", "source_last_modified_at", "source_last_modified_text",
    "source_url", "retrieved_at_utc", "collection_method",
    "collector_version",
]

SERVICE_SOURCE_FIELDS = [
    "provider_id", "birth_navi_id", "listing_role",
    "resident_prefecture_code", "resident_prefecture_name",
    "resident_municipality_code", "resident_municipality_name",
    "household_type_code", "household_type", "facility_name_displayed",
    "postnatal_care_type_code", "postnatal_care_type", "fee_text",
    "fee_includes_text", "max_use_text", "eligible_infant_age_text",
    "multiple_birth_acceptance_text", "sibling_acceptance_text",
    "service_notes_text", "source_last_modified_at",
    "source_last_modified_text", "source_url", "retrieved_at_utc",
    "collection_method", "collector_version",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def clean_text(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def import_ui_json(path: Path, snapshot_dir: Path) -> None:
    records = json.loads(path.read_text(encoding="utf-8"))
    relations = []
    services = []
    seen_relations = set()

    for item in records:
        if item.get("household_type_code") != HOUSEHOLD_TYPE_CODE:
            raise ValueError(
                f"Unexpected household type for {item.get('birth_navi_id')}"
            )
        key = (str(item["birth_navi_id"]), str(item["municipality_code"]))
        if key in seen_relations:
            raise ValueError(f"Duplicate UI relation: {key}")
        seen_relations.add(key)
        observed = item.get("services") or []
        common = {
            "provider_id": item.get("provider_id", ""),
            "birth_navi_id": str(item.get("birth_navi_id", "")),
            "listing_role": item.get("listing_role", ""),
            "resident_prefecture_code": PREFECTURE_CODE,
            "resident_prefecture_name": PREFECTURE_NAME,
            "resident_municipality_code": str(item.get("municipality_code", "")),
            "resident_municipality_name": item.get("municipality_name", ""),
            "household_type_code": HOUSEHOLD_TYPE_CODE,
            "household_type": HOUSEHOLD_TYPE_NAME,
            "facility_name_displayed": clean_text(item.get("facility_name")),
            "source_last_modified_at": item.get("source_last_modified_at", ""),
            "source_last_modified_text": clean_text(
                item.get("source_last_modified_text")
            ),
            "source_url": item.get("source_url", ""),
            "retrieved_at_utc": item.get("retrieved_at_utc", ""),
            "collection_method": "browser_ui_form_selection",
            "collector_version": COLLECTOR_VERSION,
        }
        relations.append({
            **common,
            "eligibility_text": "; ".join(
                clean_text(x) for x in (item.get("eligibility") or []) if clean_text(x)
            ),
            "overall_remarks": clean_text(item.get("overall_remarks")),
            "observed_service_count": len(observed),
            "detail_status": (
                "services_displayed" if observed
                else "no_service_details_displayed_after_selection"
            ),
        })
        for service in observed:
            name = clean_text(service.get("service_type"))
            if name not in SERVICE_CODES:
                raise ValueError(
                    f"Unknown service type for {item.get('birth_navi_id')}: {name}"
                )
            fields = service.get("fields") or {}
            services.append({
                **common,
                "postnatal_care_type_code": SERVICE_CODES[name],
                "postnatal_care_type": name,
                "fee_text": clean_text(fields.get("利用料金")),
                "fee_includes_text": clean_text(
                    fields.get("利用料金に含まれるもの")
                ),
                "max_use_text": clean_text(
                    fields.get("最大利用可能日数（回数）")
                ),
                "eligible_infant_age_text": clean_text(
                    fields.get("利用可能な月齢")
                ),
                "multiple_birth_acceptance_text": clean_text(
                    fields.get("多胎児の受け入れ")
                ),
                "sibling_acceptance_text": clean_text(
                    fields.get("きょうだい児の受け入れ")
                ),
                "service_notes_text": clean_text(fields.get("その他・備考")),
            })

    relations.sort(key=lambda r: (
        r["resident_municipality_code"], int(r["birth_navi_id"])
    ))
    services.sort(key=lambda r: (
        r["resident_municipality_code"], int(r["birth_navi_id"]),
        int(r["postnatal_care_type_code"]),
    ))
    write_csv(
        snapshot_dir / "nara_postnatal_taxable_relations.csv",
        RELATION_FIELDS,
        relations,
    )
    write_csv(
        snapshot_dir / "nara_postnatal_taxable_services.csv",
        SERVICE_SOURCE_FIELDS,
        services,
    )


def normalize_fee(raw: str) -> dict[str, str]:
    text = clean_text(raw)
    normalized = unicodedata.normalize("NFKC", text)
    compact = normalized.replace(" ", "")
    base = {
        "fee_yen": "", "fee_min_yen": "", "fee_max_yen": "",
        "fee_unit": "", "fee_note": "", "fee_normalization_status": "",
    }
    if not compact or compact in {"-", "ー", "—"}:
        return {**base, "fee_normalization_status": "not_stated"}
    if compact in {"無料", "0円"}:
        return {
            **base, "fee_yen": "0", "fee_min_yen": "0",
            "fee_max_yen": "0", "fee_normalization_status": "exact_yen",
        }
    if (
        compact in {"お問合せください", "お問い合わせください", "要確認"}
        or "ホームページをご確認ください" in compact
    ):
        return {**base, "fee_normalization_status": "contact_required"}
    if compact in {"その他に記載"}:
        return {**base, "fee_normalization_status": "not_stated"}

    range_match = re.fullmatch(
        r"(\d[\d,]*)[~～〜\-－−](\d[\d,]*)(?:円)?(?:[（(](.+)[）)])?",
        compact,
    )
    if range_match:
        low = int(range_match.group(1).replace(",", ""))
        high = int(range_match.group(2).replace(",", ""))
        return {
            **base,
            "fee_min_yen": str(min(low, high)),
            "fee_max_yen": str(max(low, high)),
            "fee_note": range_match.group(3) or "",
            "fee_normalization_status": "range_yen",
        }

    embedded_ranges = list(re.finditer(
        r"(\d[\d,]*)[~～〜\-－−](\d[\d,]*)円", compact
    ))
    if len(embedded_ranges) == 1:
        match = embedded_ranges[0]
        remainder = compact[:match.start()] + compact[match.end():]
        if not re.search(r"\d[\d,]*円", remainder):
            low = int(match.group(1).replace(",", ""))
            high = int(match.group(2).replace(",", ""))
            return {
                **base,
                "fee_min_yen": str(min(low, high)),
                "fee_max_yen": str(max(low, high)),
                "fee_note": text,
                "fee_normalization_status": "range_yen",
            }

    amounts = [
        int(x.replace(",", ""))
        for x in re.findall(r"(\d[\d,]*)円", compact)
    ]
    if amounts and "無料" in compact:
        return {
            **base,
            "fee_min_yen": "0",
            "fee_max_yen": str(max(amounts)),
            "fee_note": text,
            "fee_normalization_status": "multiple_tiers",
        }
    if len(amounts) > 1:
        return {
            **base,
            "fee_min_yen": str(min(amounts)),
            "fee_max_yen": str(max(amounts)),
            "fee_normalization_status": "multiple_tiers",
        }

    # A second tier is sometimes written without a repeated 円 suffix, for
    # example "1,300（7時間利用時）、1,700（9時間利用時）".  Comma-grouped
    # values are sufficiently currency-like to retain both as tiers here;
    # duration values in the same text are not comma-grouped.
    comma_grouped_amounts = [
        int(value.replace(",", ""))
        for value in re.findall(r"\b(\d{1,3}(?:,\d{3})+)\b", normalized)
    ]
    if len(comma_grouped_amounts) > 1:
        return {
            **base,
            "fee_min_yen": str(min(comma_grouped_amounts)),
            "fee_max_yen": str(max(comma_grouped_amounts)),
            "fee_note": text,
            "fee_normalization_status": "multiple_tiers",
        }

    exact_match = re.fullmatch(
        r"(\d[\d,]*)円?(?:/(日|回|時|泊))?(?:[（(](.+)[）)])?",
        compact,
    )
    if exact_match:
        amount = str(int(exact_match.group(1).replace(",", "")))
        unit = {"日": "per_day", "回": "per_use", "時": "per_hour",
                "泊": "per_night"}.get(exact_match.group(2), "")
        note = exact_match.group(3) or ""
        status = "exact_yen_with_note" if note else "exact_yen"
        return {
            **base, "fee_yen": amount, "fee_min_yen": amount,
            "fee_max_yen": amount, "fee_unit": unit, "fee_note": note,
            "fee_normalization_status": status,
        }

    if len(amounts) == 1:
        amount = str(amounts[0])
        unit = ""
        if re.search(r"/(?:日|1日)|/日", compact):
            unit = "per_day"
        elif re.search(r"/(?:回|1回)", compact):
            unit = "per_use"
        elif re.search(r"/(?:時間|時)|1時間あたり|時間あたり", compact):
            unit = "per_hour"
        elif re.search(r"/(?:泊|1泊)", compact):
            unit = "per_night"
        return {
            **base,
            "fee_yen": amount,
            "fee_min_yen": amount,
            "fee_max_yen": amount,
            "fee_unit": unit,
            "fee_note": text,
            "fee_normalization_status": "exact_yen_with_note",
        }

    labeled_amounts = [
        int(value.replace(",", ""))
        for value in re.findall(r"[:：]\s*(\d[\d,]*)", normalized)
    ]
    bare_amounts = labeled_amounts or comma_grouped_amounts
    if not bare_amounts and re.fullmatch(r"\d+(?:、\d+)+", compact):
        bare_amounts = [int(value) for value in compact.split("、")]
    if len(bare_amounts) > 1:
        return {
            **base,
            "fee_min_yen": str(min(bare_amounts)),
            "fee_max_yen": str(max(bare_amounts)),
            "fee_note": text,
            "fee_normalization_status": "multiple_tiers",
        }
    if len(bare_amounts) == 1:
        amount = str(bare_amounts[0])
        return {
            **base,
            "fee_yen": amount,
            "fee_min_yen": amount,
            "fee_max_yen": amount,
            "fee_note": text,
            "fee_normalization_status": "exact_yen_with_note",
        }

    return {**base, "fee_normalization_status": "unparsed"}


def provider_locations(listing_map: list[dict]) -> dict[str, dict[str, str]]:
    candidates = defaultdict(set)
    for row in listing_map:
        if row.get("listing_role") != "facility_listing":
            continue
        code = row.get("listing_municipality_code", "")
        name = row.get("listing_municipality_name", "")
        if code:
            candidates[row["provider_id"]].add((code, name))
    result = {}
    for provider_id, places in candidates.items():
        if len(places) == 1:
            code, name = next(iter(places))
            result[provider_id] = {
                "provider_location_municipality_code": code,
                "provider_location_municipality_name": name,
                "provider_location_status": "unique_standard_facility_listing",
            }
        else:
            result[provider_id] = {
                "provider_location_municipality_code": "",
                "provider_location_municipality_name": "",
                "provider_location_status": "multiple_standard_facility_municipalities",
            }
    return result


def build_outputs(root: Path, snapshot_dir: Path, derived_dir: Path,
                  quality_dir: Path) -> None:
    relations = read_csv(snapshot_dir / "nara_postnatal_taxable_relations.csv")
    services = read_csv(snapshot_dir / "nara_postnatal_taxable_services.csv")
    providers = {
        row["provider_id"]: row
        for row in read_csv(derived_dir / "providers.csv")
    }
    listing_map = read_csv(derived_dir / "provider_listing_map.csv")
    locations = provider_locations(listing_map)

    derived = []
    for row in services:
        provider = providers.get(row["provider_id"])
        if provider is None:
            raise ValueError(f"Unknown provider_id: {row['provider_id']}")
        location = locations.get(row["provider_id"], {
            "provider_location_municipality_code": "",
            "provider_location_municipality_name": "",
            "provider_location_status": "no_standard_facility_listing",
        })
        location_code = location["provider_location_municipality_code"]
        same = ""
        if location_code:
            same = "1" if location_code == row["resident_municipality_code"] else "0"
        derived.append({
            **row,
            "provider_name": provider.get("provider_name", ""),
            **location,
            "same_municipality_flag": same,
            "public_address": provider.get("public_address", ""),
            "latitude": provider.get("latitude", ""),
            "longitude": provider.get("longitude", ""),
            "coordinate_source": provider.get("coordinate_source", ""),
            "coordinate_status": provider.get("coordinate_status", ""),
            "coordinate_is_address_representative_point": provider.get(
                "coordinate_is_address_representative_point", ""
            ),
            "coordinate_representative_point_granularity": provider.get(
                "coordinate_representative_point_granularity", ""
            ),
            **normalize_fee(row["fee_text"]),
        })

    derived_fields = SERVICE_SOURCE_FIELDS[:11] + [
        "provider_name", "provider_location_municipality_code",
        "provider_location_municipality_name", "provider_location_status",
        "same_municipality_flag",
    ] + SERVICE_SOURCE_FIELDS[11:13] + [
        "fee_yen", "fee_min_yen", "fee_max_yen", "fee_unit", "fee_note",
        "fee_normalization_status",
    ] + SERVICE_SOURCE_FIELDS[13:] + [
        "public_address", "latitude", "longitude", "coordinate_source",
        "coordinate_status", "coordinate_is_address_representative_point",
        "coordinate_representative_point_granularity",
    ]
    write_csv(
        derived_dir / "nara_postnatal_taxable_fees.csv",
        derived_fields,
        derived,
    )

    relation_by_key = {
        (r["birth_navi_id"], r["resident_municipality_code"]): r
        for r in relations
    }
    services_by_key = defaultdict(list)
    for row in services:
        services_by_key[(
            row["birth_navi_id"], row["resident_municipality_code"]
        )].append(row)
    source_relations = [
        r for r in read_csv(derived_dir / "municipality_postnatal_services.csv")
        if r.get("municipality_code", "").startswith(PREFECTURE_CODE)
    ]
    discrepancies = []
    for source in source_relations:
        key = (source["birth_navi_id"], source["municipality_code"])
        if key not in relation_by_key:
            raise ValueError(f"Missing UI relation for source key: {key}")
        expected = {x for x in source["postnatal_care_type_codes"].split(";") if x}
        observed = {
            x["postnatal_care_type_code"] for x in services_by_key.get(key, [])
        }
        missing = sorted(expected - observed, key=int)
        unexpected = sorted(observed - expected, key=int)
        discrepancies.append({
            "provider_id": source["provider_id"],
            "birth_navi_id": source["birth_navi_id"],
            "resident_municipality_code": source["municipality_code"],
            "resident_municipality_name": source["municipality_name"],
            "snapshot_service_type_codes": ";".join(sorted(expected, key=int)),
            "ui_observed_service_type_codes": ";".join(sorted(observed, key=int)),
            "missing_from_ui_codes": ";".join(missing),
            "unexpected_in_ui_codes": ";".join(unexpected),
            "discrepancy_status": (
                "match" if not missing and not unexpected
                else "snapshot_ui_difference"
            ),
        })
    discrepancy_fields = list(discrepancies[0])
    write_csv(
        quality_dir / "nara_postnatal_taxable_service_discrepancies.csv",
        discrepancy_fields,
        discrepancies,
    )

    relations_by_muni = defaultdict(list)
    derived_by_muni = defaultdict(list)
    for row in relations:
        relations_by_muni[row["resident_municipality_code"]].append(row)
    for row in derived:
        derived_by_muni[row["resident_municipality_code"]].append(row)

    summary = []
    for code, name in NARA_MUNICIPALITIES:
        rels = relations_by_muni.get(code, [])
        rows = derived_by_muni.get(code, [])
        exact_statuses = {"exact_yen", "exact_yen_with_note"}
        range_statuses = {"range_yen"}
        complex_statuses = {"multiple_tiers", "unparsed"}
        no_value_statuses = {"not_stated", "contact_required"}
        present = bool(rels)
        retrieved = sorted(r["retrieved_at_utc"] for r in rels if r["retrieved_at_utc"])
        summary.append({
            "resident_prefecture_code": PREFECTURE_CODE,
            "resident_prefecture_name": PREFECTURE_NAME,
            "resident_municipality_code": code,
            "resident_municipality_name": name,
            "relation_count": len(rels),
            "distinct_provider_count": len({r["provider_id"] for r in rels}),
            "service_row_count": len(rows),
            "exact_fee_row_count": sum(
                r["fee_normalization_status"] in exact_statuses for r in rows
            ),
            "range_fee_row_count": sum(
                r["fee_normalization_status"] in range_statuses for r in rows
            ),
            "complex_fee_row_count": sum(
                r["fee_normalization_status"] in complex_statuses for r in rows
            ),
            "no_numeric_fee_row_count": sum(
                r["fee_normalization_status"] in no_value_statuses for r in rows
            ),
            "same_municipality_service_row_count": sum(
                r["same_municipality_flag"] == "1" for r in rows
            ),
            "different_municipality_service_row_count": sum(
                r["same_municipality_flag"] == "0" for r in rows
            ),
            "unknown_location_service_row_count": sum(
                r["same_municipality_flag"] == "" for r in rows
            ),
            "source_relation_status": (
                "relation_present" if present else "no_relation_in_2026_snapshot"
            ),
            "cost_collection_status": (
                "collected_from_birth_navi_ui" if present
                else "not_collected_no_relation"
            ),
            "missing_reason": (
                "" if present
                else "not_listed_in_2026_municipality_postnatal_services_snapshot"
            ),
            "retrieved_at_utc_min": retrieved[0] if retrieved else "",
            "retrieved_at_utc_max": retrieved[-1] if retrieved else "",
        })
    write_csv(
        derived_dir / "nara_municipality_postnatal_taxable_summary.csv",
        list(summary[0]),
        summary,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--ui-json", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    snapshot_dir = root / "data/snapshots/2026"
    derived_dir = root / "data/derived/2026"
    quality_dir = root / "data/quality/2026"
    if args.ui_json:
        import_ui_json(args.ui_json.resolve(), snapshot_dir)
    build_outputs(root, snapshot_dir, derived_dir, quality_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
