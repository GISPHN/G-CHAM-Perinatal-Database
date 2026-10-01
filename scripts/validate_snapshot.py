#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path


def rows(path: Path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot-dir", required=True)
    a = ap.parse_args()
    root = Path(a.snapshot_dir)

    expected = [
        x.strip()
        for x in (root / "facility_ids.txt").read_text(encoding="utf-8-sig").splitlines()
        if x.strip()
    ]
    expected_set = set(expected)

    status_rows = rows(root / "collection_status.csv")
    status_ids = [r.get("birth_navi_id", "") for r in status_rows]
    status_set = set(status_ids)
    duplicate_status_ids = len(status_ids) != len(status_set)

    unknown_status = [
        r for r in status_rows
        if (r.get("retrieval_status") or "") not in {"ok", "http_404", "http_410"}
    ]
    ok_ids = {
        r.get("birth_navi_id", "")
        for r in status_rows
        if (r.get("retrieval_status") or "") == "ok"
    }
    unavailable_rows = [
        r for r in status_rows
        if (r.get("retrieval_status") or "") in {"http_404", "http_410"}
    ]

    fac = rows(root / "facilities.csv")
    actual_ids = [r.get("birth_navi_id", "") for r in fac]
    actual_set = set(actual_ids)
    duplicate_facility_ids = len(actual_ids) != len(actual_set)

    missing_status = sorted(expected_set - status_set, key=int)
    unexpected_status = sorted(
        status_set - expected_set,
        key=lambda x: int(x) if x.isdigit() else 10**12,
    )
    missing_accessible_facilities = sorted(ok_ids - actual_set, key=int)
    unexpected_facilities = sorted(
        actual_set - ok_ids,
        key=lambda x: int(x) if x.isdigit() else 10**12,
    )

    invalid_coord = 0
    missing_coord = 0
    missing_name = 0
    hidden_addr = 0
    hidden_phone = 0
    patterns = {}

    for r in fac:
        if not (r.get("facility_name") or "").strip():
            missing_name += 1

        lat = (r.get("latitude") or "").strip()
        lon = (r.get("longitude") or "").strip()
        if not lat or not lon:
            missing_coord += 1
        else:
            try:
                la, lo = float(lat), float(lon)
                if not (20 <= la <= 50 and 120 <= lo <= 155):
                    invalid_coord += 1
            except Exception:
                invalid_coord += 1

        if (r.get("is_address_visible") or "").lower() == "false" and (r.get("address") or "").strip():
            hidden_addr += 1
        if (r.get("is_phone_number_visible") or "").lower() == "false" and (r.get("phone_number") or "").strip():
            hidden_phone += 1

        p = r.get("service_pattern") or ""
        patterns[p] = patterns.get(p, 0) + 1

    http_404_count = sum((r.get("retrieval_status") or "") == "http_404" for r in status_rows)
    http_410_count = sum((r.get("retrieval_status") or "") == "http_410" for r in status_rows)

    complete = (
        expected_set == status_set
        and not duplicate_status_ids
        and not unknown_status
        and actual_set == ok_ids
        and not duplicate_facility_ids
    )

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "sitemap_facility_count": len(expected),
        "collection_status_count": len(status_rows),
        "retrievable_facility_count": len(fac),
        "source_unavailable_count": len(unavailable_rows),
        "http_404_count": http_404_count,
        "http_410_count": http_410_count,
        "complete": complete,
        "duplicate_status_ids": duplicate_status_ids,
        "duplicate_facility_ids": duplicate_facility_ids,
        "missing_status_count": len(missing_status),
        "unexpected_status_count": len(unexpected_status),
        "missing_accessible_facility_count": len(missing_accessible_facilities),
        "unexpected_facility_count": len(unexpected_facilities),
        "unknown_retrieval_status_count": len(unknown_status),
        "missing_name_count": missing_name,
        "missing_coordinate_count": missing_coord,
        "invalid_coordinate_count": invalid_coord,
        "hidden_address_violation_count": hidden_addr,
        "hidden_phone_violation_count": hidden_phone,
        "service_pattern_counts": patterns,
        "missing_status_ids_sample": missing_status[:20],
        "unexpected_status_ids_sample": unexpected_status[:20],
        "unavailable_ids_sample": [
            r.get("birth_navi_id", "") for r in unavailable_rows[:20]
        ],
    }

    (root / "validation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    return 2 if (
        not complete
        or invalid_coord
        or hidden_addr
        or hidden_phone
        or missing_name
    ) else 0


if __name__ == "__main__":
    raise SystemExit(main())
