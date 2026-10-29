#!/usr/bin/env python3
"""Collect and build taxable-household postnatal-care tables by prefecture scope.

Western Japan is defined here as the 23 prefectures in Kinki, Chugoku,
Shikoku, and Kyushu/Okinawa. Mie is excluded because this project uses the
23-prefecture operational definition rather than the broader Kinki grouping
shown in the Birth Navi selector.

The default scope remains western Japan for backward compatibility. Passing
all 47 prefecture codes and ``--output-prefix nationwide`` creates the
nationwide tables.

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
COLLECTOR_VERSION = "postnatal-taxable-loader-1.1.0"
HOUSEHOLD_TYPE_CODE = "1"
HOUSEHOLD_TYPE_NAME = "住民税課税世帯"

PREFECTURES = {
    "01": "北海道", "02": "青森県", "03": "岩手県", "04": "宮城県",
    "05": "秋田県", "06": "山形県", "07": "福島県", "08": "茨城県",
    "09": "栃木県", "10": "群馬県", "11": "埼玉県", "12": "千葉県",
    "13": "東京都", "14": "神奈川県", "15": "新潟県", "16": "富山県",
    "17": "石川県", "18": "福井県", "19": "山梨県", "20": "長野県",
    "21": "岐阜県", "22": "静岡県", "23": "愛知県", "24": "三重県",
    "25": "滋賀県", "26": "京都府", "27": "大阪府", "28": "兵庫県",
    "29": "奈良県", "30": "和歌山県", "31": "鳥取県", "32": "島根県",
    "33": "岡山県", "34": "広島県", "35": "山口県", "36": "徳島県",
    "37": "香川県", "38": "愛媛県", "39": "高知県", "40": "福岡県",
    "41": "佐賀県", "42": "長崎県", "43": "熊本県", "44": "大分県",
    "45": "宮崎県", "46": "鹿児島県", "47": "沖縄県",
}
WESTERN_PREFECTURE_CODES = tuple(f"{code:02d}" for code in range(25, 48))

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
        except urllib.error.HTTPError as error:
            if error.code in {404, 410}:
                return {
                    "birth_navi_id": relation["birth_navi_id"],
                    "municipality_code": relation["municipality_code"],
                    "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
                    "source_url": source_url,
                    "http_status": error.code,
                    "error_status": "source_page_not_found",
                }
            if attempt + 1 == retries:
                raise
            time.sleep(2 ** attempt)
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
        root / "data/derived/2026/municipality_postnatal_services