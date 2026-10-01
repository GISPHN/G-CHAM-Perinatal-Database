#!/usr/bin/env python3
"""Validate and adapt a successful shard artifact from an earlier workflow run."""
from __future__ import annotations

import argparse
import csv
from pathlib import Path


def read_ids(path: Path) -> list[str]:
    return [
        x.strip()
        for x in path.read_text(encoding="utf-8-sig").splitlines()
        if x.strip()
    ]


def read_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tables-dir", required=True)
    ap.add_argument("--ids-file", required=True)
    a = ap.parse_args()

    tables = Path(a.tables_dir)
    facilities_path = tables / "facilities.csv"
    if not facilities_path.exists():
        print("No facilities.csv in prior shard artifact.")
        return 2

    expected = read_ids(Path(a.ids_file))
    facilities = read_csv(facilities_path)
    actual = [r.get("birth_navi_id", "") for r in facilities]

    if len(actual) != len(set(actual)):
        print("Prior shard has duplicate facility IDs.")
        return 3

    if set(actual) != set(expected):
        print(
            f"Prior shard ID mismatch: expected={len(expected)} "
            f"actual={len(actual)} missing={len(set(expected)-set(actual))} "
            f"unexpected={len(set(actual)-set(expected))}"
        )
        return 4

    status_fields = [
        "birth_navi_id",
        "source_url",
        "retrieved_at_utc",
        "http_status",
        "retrieval_status",
        "source_last_modified_at",
        "raw_response_sha256",
        "parser_version",
    ]
    status_rows = []
    by_id = {r.get("birth_navi_id", ""): r for r in facilities}
    for fid in expected:
        r = by_id[fid]
        status_rows.append(
            {
                "birth_navi_id": fid,
                "source_url": r.get("source_url", ""),
                "retrieved_at_utc": r.get("retrieved_at_utc", ""),
                "http_status": "200",
                "retrieval_status": "ok",
                "source_last_modified_at": r.get("source_last_modified_at", ""),
                "raw_response_sha256": r.get("raw_response_sha256", ""),
                "parser_version": r.get("parser_version", ""),
            }
        )

    out = tables / "collection_status.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=status_fields)
        w.writeheader()
        w.writerows(status_rows)

    print(f"Prior shard validated and adapted: {len(status_rows)} facilities.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
