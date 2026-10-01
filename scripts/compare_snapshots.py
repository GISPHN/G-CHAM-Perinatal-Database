#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from pathlib import Path

SINGLE = ["facilities", "facility_detail", "delivery", "prenatal"]
LONG = {
    "prenatal_checkup_details": ["period"],
    "prenatal_options": ["checkup_item"],
    "pregnancy_checkups": ["pregnancy_checkup_type"],
    "postnatal_services": ["postnatal_care_type_code"],
    "outpatient_times": ["day_of_week_code"],
    "room_costs": ["room_type_code"],
    "painless_delivery_costs": ["item"],
}
IGNORE = {"retrieved_at_utc", "raw_response_sha256", "parser_version", "source_url"}
FIELDS = [
    "snapshot_year",
    "previous_snapshot_year",
    "birth_navi_id",
    "change_type",
    "table",
    "record_key",
    "field",
    "old_value",
    "new_value",
]


def read(path: Path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def idx(rows):
    return {r["birth_navi_id"]: r for r in rows if r.get("birth_navi_id")}


def lkey(r, keys):
    return (
        r.get("birth_navi_id", ""),
        "|".join(f"{k}={r.get(k, '')}" for k in keys),
    )


def append_unique(path: Path, newrows):
    existing = set()
    if path.exists():
        for r in read(path):
            existing.add(tuple(r.get(k, "") for k in FIELDS))

    newrows = [
        r
        for r in newrows
        if tuple(r.get(k, "") for k in FIELDS) not in existing
    ]

    mode = "a" if path.exists() else "w"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open(mode, encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if mode == "w":
            w.writeheader()
        w.writerows(newrows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshots-root", required=True)
    ap.add_argument("--current-year", type=int, required=True)
    ap.add_argument("--history-dir", required=True)
    a = ap.parse_args()

    root = Path(a.snapshots_root)
    cur = root / str(a.current_year)
    hist = Path(a.history_dir)
    hist.mkdir(parents=True, exist_ok=True)

    fac = read(cur / "facilities.csv")
    status = read(cur / "collection_status.csv")

    summary = {
        "snapshot_year": str(a.current_year),
        "sitemap_facility_count": str(len(status)),
        "available_facility_count": str(len(fac)),
        "source_unavailable_count": str(
            sum(
                (r.get("retrieval_status") or "") in {"http_404", "http_410"}
                for r in status
            )
        ),
        "prenatal_checkup_listed": str(
            sum(r.get("prenatal_checkup_listed") == "1" for r in fac)
        ),
        "delivery_listed": str(
            sum(r.get("delivery_listed") == "1" for r in fac)
        ),
        "postnatal_care_listed": str(
            sum(r.get("postnatal_care_listed") == "1" for r in fac)
        ),
        "all_three_services": str(
            sum(r.get("service_count") == "3" for r in fac)
        ),
    }

    summary_path = hist / "annual_summary.csv"
    old = [
        r
        for r in read(summary_path)
        if r.get("snapshot_year") != str(a.current_year)
    ]
    with summary_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summary))
        w.writeheader()
        w.writerows(
            sorted(old + [summary], key=lambda r: int(r["snapshot_year"]))
        )

    prevs = sorted(
        int(p.name)
        for p in root.iterdir()
        if p.is_dir() and p.name.isdigit() and int(p.name) < a.current_year
    )
    if not prevs:
        print("No prior snapshot; no changes emitted.")
        return 0

    py = prevs[-1]
    prev = root / str(py)
    changes = []

    # Facility presence is defined by sitemap membership, not by whether a stale
    # sitemap URL returned a retrievable detail page on the observation date.
    old_status = idx(read(prev / "collection_status.csv"))
    new_status = idx(status)

    for fid in sorted(set(new_status) - set(old_status), key=int):
        changes.append(
            {
                "snapshot_year": str(a.current_year),
                "previous_snapshot_year": str(py),
                "birth_navi_id": fid,
                "change_type": "facility_added",
                "table": "collection_status",
                "record_key": "",
                "field": "sitemap_presence",
                "old_value": "0",
                "new_value": "1",
            }
        )

    for fid in sorted(set(old_status) - set(new_status), key=int):
        changes.append(
            {
                "snapshot_year": str(a.current_year),
                "previous_snapshot_year": str(py),
                "birth_navi_id": fid,
                "change_type": "facility_removed",
                "table": "collection_status",
                "record_key": "",
                "field": "sitemap_presence",
                "old_value": "1",
                "new_value": "0",
            }
        )

    # Track changes in retrievability separately from facility presence.
    for fid in sorted(set(old_status) & set(new_status), key=int):
        old_retrieval = old_status[fid].get("retrieval_status", "")
        new_retrieval = new_status[fid].get("retrieval_status", "")
        if old_retrieval != new_retrieval:
            changes.append(
                {
                    "snapshot_year": str(a.current_year),
                    "previous_snapshot_year": str(py),
                    "birth_navi_id": fid,
                    "change_type": "retrieval_status_changed",
                    "table": "collection_status",
                    "record_key": "",
                    "field": "retrieval_status",
                    "old_value": old_retrieval,
                    "new_value": new_retrieval,
                }
            )

    # Compare facility-level values only for years in which a retrievable record
    # exists in both snapshots.
    for table in SINGLE:
        old_rows = idx(read(prev / f"{table}.csv"))
        new_rows = idx(read(cur / f"{table}.csv"))
        for fid in sorted(set(old_rows) & set(new_rows), key=int):
            for field in sorted(
                (set(old_rows[fid]) | set(new_rows[fid]))
                - {"birth_navi_id"}
                - IGNORE
            ):
                x = old_rows[fid].get(field, "")
                y = new_rows[fid].get(field, "")
                if x != y:
                    changes.append(
                        {
                            "snapshot_year": str(a.current_year),
                            "previous_snapshot_year": str(py),
                            "birth_navi_id": fid,
                            "change_type": "value_changed",
                            "table": table,
                            "record_key": "",
                            "field": field,
                            "old_value": x,
                            "new_value": y,
                        }
                    )

    for table, keys in LONG.items():
        old_rows = {
            lkey(r, keys): r for r in read(prev / f"{table}.csv")
        }
        new_rows = {
            lkey(r, keys): r for r in read(cur / f"{table}.csv")
        }

        for k in sorted(
            set(old_rows) | set(new_rows),
            key=lambda x: (int(x[0]), x[1]),
        ):
            fid, record_key = k

            if k not in old_rows:
                changes.append(
                    {
                        "snapshot_year": str(a.current_year),
                        "previous_snapshot_year": str(py),
                        "birth_navi_id": fid,
                        "change_type": "record_added",
                        "table": table,
                        "record_key": record_key,
                        "field": "record",
                        "old_value": "",
                        "new_value": "present",
                    }
                )
                continue

            if k not in new_rows:
                changes.append(
                    {
                        "snapshot_year": str(a.current_year),
                        "previous_snapshot_year": str(py),
                        "birth_navi_id": fid,
                        "change_type": "record_removed",
                        "table": table,
                        "record_key": record_key,
                        "field": "record",
                        "old_value": "present",
                        "new_value": "",
                    }
                )
                continue

            for field in sorted(
                (set(old_rows[k]) | set(new_rows[k]))
                - {"birth_navi_id"}
                - set(keys)
                - IGNORE
            ):
                x = old_rows[k].get(field, "")
                y = new_rows[k].get(field, "")
                if x != y:
                    changes.append(
                        {
                            "snapshot_year": str(a.current_year),
                            "previous_snapshot_year": str(py),
                            "birth_navi_id": fid,
                            "change_type": "value_changed",
                            "table": table,
                            "record_key": record_key,
                            "field": field,
                            "old_value": x,
                            "new_value": y,
                        }
                    )

    append_unique(hist / "changes.csv", changes)
    print(f"Compared {py} -> {a.current_year}; changes: {len(changes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
