#!/usr/bin/env python3
"""Collect and build taxable-household postnatal-care tables for western Japan.

Western Japan is defined here as the 23 prefectures in Kinki, Chugoku,
Shikoku, and Kyushu/Okinawa. Mie is excluded because this project uses the
23-prefecture operational definition rather than the broader Kinki grouping
shown in the Birth Navi selector.

The collector requests the public Birth Navi facility page with the same
resident municipality and household selections used by the browser form. It
decodes the React Router loader payload, keeps a restartable local cache, and
then produces source, derived, municipality-summary, and discrepancy tables.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from build_nara_postnatal_taxable import normalize_fee, provider_locations


BASE_URL = "https://birth-navi.mhlw.go.jp"
COLLECTOR_VERSION = "western-japan-loader-1.0.0"
HOUSEHOLD_TYPE_CODE = "1"
HOUSEHOLD_TYPE_NAME = "住民税課税世帯"

PREFECTURES = {
    "25": "滋賀県", "26": "京都府", "27": "大阪府", "28": "兵庫県",
    "29": "奈良県", "30": "和歌山県", "31": "鳥取県", "32": "島根県",
    "33": "岡山県", "34": "広島県", "35": "山口県", "36": "徳島県",
    "37": "香川県", "38": "愛媛県", "39": "高知県", "40": "福岡県",
    "41": "佐賀県", "42": "長崎県", "43": "熊本県", "44": "大分県",
    "45": "宮崎県", "46": "鹿児島県", "47": "沖縄県",
}

SERVICE_NAMES = {
    1: "短期入所（ショートステイ）型",
    2: "通所（デイサービス）型（個別）",
    3: "通所（デイサービス）型（集団）",
    4: "居宅訪問（アウトリーチ）型",
}
USAGE_TYPE_NAMES = {
    1: "どなたでも利用可能",
    2: "当該施設で分娩する方のみ",
    3: "当該施設で妊婦健診を受診した方のみ",
}
INCLUDED_SERVICE_NAMES = {
    1: "母の食事代", 2: "ミルク代", 3: "離乳食代",
    4: "紙おむつ代", 5: "個室使用料",
    6: "哺乳瓶の消毒に係る費用", 7: "衣類の洗濯に係る費用",
}
INCLUDED_SERVICE_ORDER = {
    1: [1, 2, 3, 4, 5, 6, 7],
    2: [1, 2, 3, 4, 5, 6],
    3: [1, 2, 3, 4, 6],
    4: [],
}

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
    "postnatal_care_type_code", "postnatal_care_type",
    "postnatal_care_option_index", "postnatal_care_source_id", "fee_text",
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
        writer = csv.DictWriter(
            f, fieldnames=fields, extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def clean_text(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def is_numeric_text(value: str) -> bool:
    return bool(re.fullmatch(r"-?\d+(?:\.\d+)?", value))


def display_value(value, suffix: str = "") -> str:
    """Reproduce the public UI formatter used for costs and day counts."""
    text = "ー" if value is None or value == "" else clean_text(value)
    if is_numeric_text(text):
        number = int(float(text))
        return f"{number:,}{suffix}"
    return text


def display_age(min_month, max_month) -> str:
    if min_month is not None and max_month is not None:
        return f"生後{min_month}ヶ月 ~ 生後{max_month}ヶ月"
    if min_month is not None:
        return f"生後{min_month}ヶ月以上"
    if max_month is not None:
        return f"生後{max_month}ヶ月まで"
    return "ー"


def display_acceptance(flag, cost) -> str:
    if flag is None:
        return "ー"
    if not flag:
        return "なし"
    return f"あり / {display_value(cost or 'ー', '円')}"


def display_included_services(service_type: int, codes: list[int] | None) -> str:
    allowed = INCLUDED_SERVICE_ORDER.get(service_type, [])
    observed = set(codes or [])
    labels = [INCLUDED_SERVICE_NAMES[x] for x in allowed if x in observed]
    return "、".join(labels) if labels else "ー"


def format_modified_at(value: str) -> str:
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        dt = dt.astimezone(ZoneInfo("Asia/Tokyo"))
        return f"※{dt.year}年{dt.month}月{dt.day}日更新"
    except ValueError:
        return ""


def extract_loader_payload(page_html: str) -> dict:
    scripts = [
        html.unescape(x)
        for x in re.findall(r"<script[^>]*>(.*?)</script>", page_html, re.S)
    ]
    for script in scripts:
        if "streamController.enqueue" not in script:
            continue
        match = re.search(r"enqueue\((.*)\);\s*$", script, re.S)
        if not match:
            continue
        serialized = json.loads(match.group(1))
        values = json.loads(serialized)
        memo: dict[int, object] = {}

        def hydrate(index: int):
            if index < 0:
                return None
            if index in memo:
                return memo[index]
            item = values[index]
            if isinstance(item, dict):
                result = {}
                memo[index] = result
                for key_ref, value_ref in item.items():
                    if key_ref.startswith("_") and key_ref[1:].isdigit():
                        key = hydrate(int(key_ref[1:]))
                    else:
                        key = key_ref
                    result[key] = (
                        hydrate(value_ref) if isinstance(value_ref, int)
                        else value_ref
                    )
                return result
            if isinstance(item, list):
                result = []
                memo[index] = result
                result.extend(
                    hydrate(value) if isinstance(value, int) else value
                    for value in item
                )
                return result
            memo[index] = item
            return item

        root = hydrate(0)
        try:
            return root["loaderData"]["routes/FacilityDetail"]
        except (KeyError, TypeError) as error:
            raise ValueError("FacilityDetail loader data was not found") from error
    raise ValueError("React Router loader payload was not found")


class RequestStartLimiter:
    def __init__(self, interval_seconds: float):
        self.interval_seconds = interval_seconds
        self.lock = threading.Lock()
        self.next_start = 0.0

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            delay = max(0.0, self.next_start - now)
            self.next_start = max(now, self.next_start) + self.interval_seconds
        if delay:
            time.sleep(delay)


def fetch_json(url: str, limiter: RequestStartLimiter, retries: int = 4) -> dict:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": (
            "G-CHAM-Perinatal-Database/2026 "
            "(public research collector; sequential rate limited access)"
        ),
    }
    for attempt in range(retries):
        limiter.wait()
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            if attempt + 1 == retries:
                raise
            time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


def fetch_relation_page(
    relation: dict[str, str], limiter: RequestStartLimiter, retries: int = 4
) -> dict:
    query = urllib.parse.urlencode({
        "municipality_code": relation["municipality_code"],
        "household_type": HOUSEHOLD_TYPE_CODE,
    })
    source_url = f"{BASE_URL}/facilities/{relation['birth_navi_id']}"
    url = f"{source_url}?{query}"
    headers = {
        "Accept": "text/html",
        "User-Agent": (
            "G-CHAM-Perinatal-Database/2026 "
            "(public research collector; sequential rate limited access)"
        ),
    }
    for attempt in range(retries):
        limiter.wait()
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=60) as response:
                page_html = response.read().decode("utf-8")
            loader = extract_loader_payload(page_html)
            return {
                "birth_navi_id": relation["birth_navi_id"],
                "municipality_code": relation["municipality_code"],
                "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
                "source_url": source_url,
                "loader": loader,
            }
        except (
            urllib.error.URLError, TimeoutError, UnicodeDecodeError,
            json.JSONDecodeError, ValueError,
        ):
            if attempt + 1 == retries:
                raise
            time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


def cache_path(cache_dir: Path, relation: dict[str, str]) -> Path:
    return cache_dir / (
        f"{relation['birth_navi_id']}_"
        f"{relation['municipality_code']}_{HOUSEHOLD_TYPE_CODE}.json"
    )


def write_json_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def collect_relations(
    relations: list[dict[str, str]], cache_dir: Path, workers: int,
    interval_seconds: float, force: bool,
) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    pending = [r for r in relations if force or not cache_path(cache_dir, r).exists()]
    print(f"relations={len(relations)} cached={len(relations)-len(pending)} pending={len(pending)}")
    if not pending:
        return
    limiter = RequestStartLimiter(interval_seconds)
    errors = []

    def task(relation):
        result = fetch_relation_page(relation, limiter)
        write_json_atomic(cache_path(cache_dir, relation), result)
        return relation

    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(task, relation): relation for relation in pending}
        for future in as_completed(futures):
            relation = futures[future]
            try:
                future.result()
                completed += 1
                if completed % 25 == 0 or completed == len(pending):
                    print(f"completed={completed}/{len(pending)}", flush=True)
            except Exception as error:  # the cache permits a safe rerun
                errors.append((relation, repr(error)))
                print(
                    "ERROR",
                    relation["birth_navi_id"],
                    relation["municipality_code"],
                    repr(error),
                    flush=True,
                )
    if errors:
        raise RuntimeError(f"{len(errors)} relation requests failed; rerun to resume")


def collect_municipality_catalog(
    prefecture_codes: list[str], cache_file: Path,
    interval_seconds: float, force: bool,
) -> list[dict[str, str]]:
    if cache_file.exists() and not force:
        return json.loads(cache_file.read_text(encoding="utf-8"))["municipalities"]
    limiter = RequestStartLimiter(interval_seconds)

    def fetch_prefecture(code: str) -> dict:
        query = urllib.parse.urlencode({"prefectureIds": int(code)})
        return fetch_json(
            f"{BASE_URL}/api/municipalities.json?{query}", limiter
        )

    responses = []
    with ThreadPoolExecutor(max_workers=min(6, len(prefecture_codes))) as executor:
        futures = {
            executor.submit(fetch_prefecture, code): code
            for code in prefecture_codes
        }
        for future in as_completed(futures):
            responses.append((futures[future], future.result()))
    municipalities = []
    for requested_code, data in responses:
        returned = data.get("prefectures", [])
        if len(returned) != 1:
            raise ValueError(
                f"Unexpected municipality response for prefecture {requested_code}"
            )
        prefecture = returned[0]
        returned_code = str(prefecture["id"]).zfill(2)
        if returned_code != requested_code:
            raise ValueError(
                f"Requested prefecture {requested_code}, received {returned_code}"
            )
        for municipality in prefecture.get("municipalities", []):
            municipalities.append({
                "resident_prefecture_code": returned_code,
                "resident_prefecture_name": prefecture["name"],
                "resident_municipality_code": str(municipality["code"]),
                "resident_municipality_name": municipality["name"],
            })
    municipalities.sort(key=lambda row: row["resident_municipality_code"])
    write_json_atomic(cache_file, {
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "prefecture_codes": prefecture_codes,
        "municipalities": municipalities,
    })
    return municipalities


def relation_rows_for_scope(root: Path, prefecture_codes: list[str]) -> list[dict[str, str]]:
    source = read_csv(
        root / "data/derived/2026/municipality_postnatal_services.csv"
    )
    allowed = set(prefecture_codes)
    rows = [r for r in source if r["municipality_code"][:2] in allowed]
    rows.sort(key=lambda r: (r["municipality_code"], int(r["birth_navi_id"])))
    keys = [(r["birth_navi_id"], r["municipality_code"]) for r in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate municipality and Birth Navi relation key")
    return rows


def load_observations(
    relations: list[dict[str, str]], cache_dir: Path,
) -> list[tuple[dict[str, str], dict]]:
    result = []
    missing = []
    for relation in relations:
        path = cache_path(cache_dir, relation)
        if not path.exists():
            missing.append(path.name)
            continue
        result.append((relation, json.loads(path.read_text(encoding="utf-8"))))
    if missing:
        raise FileNotFoundError(
            f"Missing {len(missing)} cache files; run collection first"
        )
    return result


def make_source_rows(observations) -> tuple[list[dict], list[dict]]:
    relations = []
    services = []
    for source_relation, observation in observations:
        loader = observation["loader"]
        facility = loader["facility"]
        selected = loader.get("postnatalCareData") or {}
        municipal = selected.get("municipalityPostnatalCare")
        care = municipal.get("postnatalCare", {}) if municipal else {}
        care_types = care.get("postnatalCareTypes") or []
        prefecture_code = source_relation["municipality_code"][:2]
        usage_types = care.get("usageTypes") or []
        if usage_types:
            eligibility = "; ".join(
                USAGE_TYPE_NAMES[x] for x in usage_types if x in USAGE_TYPE_NAMES
            )
        elif care.get("usageTypeOther"):
            eligibility = "備考欄に記載"
        else:
            eligibility = "ー" if municipal else ""
        modified_at = facility.get("lastModifiedAt", "")
        common = {
            "provider_id": source_relation["provider_id"],
            "birth_navi_id": source_relation["birth_navi_id"],
            "listing_role": source_relation["listing_role"],
            "resident_prefecture_code": prefecture_code,
            "resident_prefecture_name": PREFECTURES[prefecture_code],
            "resident_municipality_code": source_relation["municipality_code"],
            "resident_municipality_name": source_relation["municipality_name"],
            "household_type_code": HOUSEHOLD_TYPE_CODE,
            "household_type": HOUSEHOLD_TYPE_NAME,
            "facility_name_displayed": clean_text(facility.get("name")),
            "source_last_modified_at": modified_at,
            "source_last_modified_text": format_modified_at(modified_at),
            "source_url": observation["source_url"],
            "retrieved_at_utc": observation["retrieved_at_utc"],
            "collection_method": "public_facility_page_loader_query",
            "collector_version": COLLECTOR_VERSION,
        }
        detail_status = (
            "services_displayed" if care_types
            else "no_service_details_displayed_after_selection"
        )
        relations.append({
            **common,
            "eligibility_text": eligibility,
            "overall_remarks": (
                clean_text(care.get("usageTypeOther"))
                if care.get("usageTypeOther") is not None else ("ー" if municipal else "")
            ),
            "observed_service_count": len(care_types),
            "detail_status": detail_status,
        })

        option_index = defaultdict(int)
        municipal_types = {
            int(row["type"]): row for row in (municipal.get("types") or [])
        } if municipal else {}
        for item in sorted(care_types, key=lambda x: (int(x["type"]), int(x.get("id", 0)))):
            service_type = int(item["type"])
            option_index[service_type] += 1
            household_rows = [
                x for x in (item.get("postnatalCareHouseholdType") or [])
                if str(x.get("type")) == HOUSEHOLD_TYPE_CODE
            ]
            household = household_rows[0] if household_rows else {}
            if service_type == 4:
                included = ""
                multiple = ""
                sibling = ""
                notes = ""
            else:
                included = display_included_services(
                    service_type, household.get("includedServices")
                )
                multiple = display_acceptance(
                    item.get("canMultipleBabies"), item.get("multipleBabiesCost")
                )
                sibling = display_acceptance(
                    item.get("canSibling"), item.get("siblingCost")
                )
                notes = (
                    clean_text(household.get("includedServiceOther"))
                    if household.get("includedServiceOther") is not None else "ー"
                )
            services.append({
                **common,
                "postnatal_care_type_code": str(service_type),
                "postnatal_care_type": SERVICE_NAMES.get(
                    service_type, f"code:{service_type}"
                ),
                "postnatal_care_option_index": option_index[service_type],
                "postnatal_care_source_id": item.get("id", ""),
                "fee_text": display_value(household.get("cost"), "円"),
                "fee_includes_text": included,
                "max_use_text": display_value(
                    municipal_types.get(service_type, {}).get("maxAvailableDays"),
                    "日間",
                ),
                "eligible_infant_age_text": display_age(
                    item.get("minAvailableMonth"), item.get("maxAvailableMonth")
                ),
                "multiple_birth_acceptance_text": multiple,
                "sibling_acceptance_text": sibling,
                "service_notes_text": notes,
            })
    return relations, services


def build_outputs(
    root: Path, prefecture_codes: list[str], cache_dir: Path,
    municipality_catalog: list[dict[str, str]],
) -> None:
    snapshot_dir = root / "data/snapshots/2026"
    derived_dir = root / "data/derived/2026"
    quality_dir = root / "data/quality/2026"
    source_relations = relation_rows_for_scope(root, prefecture_codes)
    observations = load_observations(source_relations, cache_dir)
    relations, services = make_source_rows(observations)
    write_csv(
        snapshot_dir / "western_japan_postnatal_taxable_relations.csv",
        RELATION_FIELDS, relations,
    )
    write_csv(
        snapshot_dir / "western_japan_postnatal_taxable_services.csv",
        SERVICE_SOURCE_FIELDS, services,
    )

    providers = {
        row["provider_id"]: row
        for row in read_csv(derived_dir / "providers.csv")
    }
    locations = provider_locations(
        read_csv(derived_dir / "provider_listing_map.csv")
    )
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
            same = (
                "1" if location_code == row["resident_municipality_code"] else "0"
            )
        derived.append({
            **row,
            "provider_name": provider.get("provider_name", ""),
            **location,
            "same_municipality_flag": same,
            **normalize_fee(row["fee_text"]),
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
        })
    derived_fields = SERVICE_SOURCE_FIELDS[:11] + [
        "provider_name", "provider_location_municipality_code",
        "provider_location_municipality_name", "provider_location_status",
        "same_municipality_flag",
    ] + SERVICE_SOURCE_FIELDS[11:15] + [
        "fee_yen", "fee_min_yen", "fee_max_yen", "fee_unit", "fee_note",
        "fee_normalization_status",
    ] + SERVICE_SOURCE_FIELDS[15:] + [
        "public_address", "latitude", "longitude", "coordinate_source",
        "coordinate_status", "coordinate_is_address_representative_point",
        "coordinate_representative_point_granularity",
    ]
    write_csv(
        derived_dir / "western_japan_postnatal_taxable_fees.csv",
        derived_fields, derived,
    )

    observed_by_key = defaultdict(list)
    for row in services:
        observed_by_key[(
            row["birth_navi_id"], row["resident_municipality_code"]
        )].append(row)
    discrepancies = []
    for source in source_relations:
        key = (source["birth_navi_id"], source["municipality_code"])
        expected = {
            x for x in source["postnatal_care_type_codes"].split(";") if x
        }
        observed = {
            row["postnatal_care_type_code"] for row in observed_by_key.get(key, [])
        }
        missing = sorted(expected - observed, key=int)
        unexpected = sorted(observed - expected, key=int)
        discrepancies.append({
            "provider_id": source["provider_id"],
            "birth_navi_id": source["birth_navi_id"],
            "resident_prefecture_code": source["municipality_code"][:2],
            "resident_prefecture_name": PREFECTURES[source["municipality_code"][:2]],
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
    write_csv(
        quality_dir / "western_japan_postnatal_taxable_service_discrepancies.csv",
        list(discrepancies[0]), discrepancies,
    )

    relations_by_municipality = defaultdict(list)
    derived_by_municipality = defaultdict(list)
    for row in relations:
        relations_by_municipality[row["resident_municipality_code"]].append(row)
    for row in derived:
        derived_by_municipality[row["resident_municipality_code"]].append(row)
    summary = []
    exact_statuses = {"exact_yen", "exact_yen_with_note"}
    range_statuses = {"range_yen"}
    complex_statuses = {"multiple_tiers", "unparsed"}
    no_value_statuses = {"not_stated", "contact_required"}
    for municipality in municipality_catalog:
        if municipality["resident_prefecture_code"] not in prefecture_codes:
            continue
        code = municipality["resident_municipality_code"]
        rels = relations_by_municipality.get(code, [])
        rows = derived_by_municipality.get(code, [])
        retrieved = sorted(
            row["retrieved_at_utc"] for row in rels if row["retrieved_at_utc"]
        )
        present = bool(rels)
        summary.append({
            **municipality,
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
                "service_rows_collected" if rows
                else (
                    "no_service_details_displayed" if present
                    else "no_relation_in_2026_snapshot"
                )
            ),
            "missing_reason": (
                "" if rows else (
                    "all_relation_selections_displayed_no_service_details"
                    if present else
                    "not_listed_in_2026_municipality_postnatal_services_snapshot"
                )
            ),
            "retrieved_at_utc_min": retrieved[0] if retrieved else "",
            "retrieved_at_utc_max": retrieved[-1] if retrieved else "",
        })
    summary.sort(key=lambda row: row["resident_municipality_code"])
    write_csv(
        derived_dir / "western_japan_municipality_postnatal_taxable_summary.csv",
        list(summary[0]), summary,
    )


def parse_prefecture_codes(raw: str) -> list[str]:
    codes = [x.strip().zfill(2) for x in raw.split(",") if x.strip()]
    unknown = sorted(set(codes) - set(PREFECTURES))
    if unknown:
        raise ValueError(f"Codes outside the western Japan scope: {unknown}")
    return sorted(set(codes))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument(
        "--prefecture-codes", default=",".join(PREFECTURES),
        help="Comma-separated two-digit prefecture codes within the scope",
    )
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--request-start-interval", type=float, default=0.25)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--collect-only", action="store_true")
    parser.add_argument("--build-only", action="store_true")
    args = parser.parse_args()
    if args.collect_only and args.build_only:
        parser.error("--collect-only and --build-only cannot be combined")
    if args.workers < 1 or args.workers > 8:
        parser.error("--workers must be between 1 and 8")
    if args.request_start_interval < 0.2:
        parser.error("--request-start-interval must be at least 0.2 seconds")

    root = args.root.resolve()
    prefecture_codes = parse_prefecture_codes(args.prefecture_codes)
    scope = "-".join(prefecture_codes)
    cache_dir = root / "work/western_japan_postnatal_taxable_cache/relations"
    municipality_cache = (
        root / "work/western_japan_postnatal_taxable_cache"
        / f"municipalities_{scope}.json"
    )
    source_relations = relation_rows_for_scope(root, prefecture_codes)
    if not args.build_only:
        municipalities = collect_municipality_catalog(
            prefecture_codes, municipality_cache,
            args.request_start_interval, args.force,
        )
        collect_relations(
            source_relations, cache_dir, args.workers,
            args.request_start_interval, args.force,
        )
    else:
        municipalities = collect_municipality_catalog(
            prefecture_codes, municipality_cache,
            args.request_start_interval, False,
        )
    if not args.collect_only:
        build_outputs(root, prefecture_codes, cache_dir, municipalities)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
