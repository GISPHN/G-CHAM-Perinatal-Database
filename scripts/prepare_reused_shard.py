#!/usr/bin/env python3
"""Validate and adapt a full or partial shard artifact from an earlier run.

A prior artifact is reusable only when every completed Birth Navi ID belongs to
the current deterministic shard. Completed IDs are removed from the pending list;
the collector then fetches only the missing IDs and appends to the preserved CSVs.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path


STATUS_FIELDS = [
    "birth_navi_id",
    "source_url",
    "retrieved_at_utc",
    "http_status",
    "retrieval_status",
    "source_last_modified_at",
    "raw_response_sha256",
    "parser_version",
]


def read_ids(path: Path) -> list[str]:
    return [
        x.strip()
        for x in path.read_text(encoding="utf-8-sig").splitlines()
        if x.strip()
    ]


def read_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_ids(path: Path, ids: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(ids)
    path.write_text(text + ("\n" if ids else ""), encoding="utf-8")


def synthesize_status_from_facilities(tables: Path, facilities):
    rows = []
    for r in facilities:
        fid = r.get("birth_navi_id", "")
        if not fid:
            continue
        rows.append(
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
        w = csv.DictWriter(f, fieldnames=STATUS_FIELDS)
        w.writeheader()
        w.writerows(rows)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tables-dir", required=True)
    ap.add_argument("--ids-file", required=True)
    ap.add_argument("--pending-out", required=True)
    a = ap.parse_args()

    tables = Path(a.tables_dir)
    expected = read_ids(Path(a.ids_file))
    expected_set = set(expected)

    status_path = tables / "collection_status.csv"
    facilities_path = tables / "facilities.csv"

    if status_path.exists():
        status_rows = read_csv(status_path)
    elif facilities_path.exists():
        facilities = read_csv(facilities_path)
        status_rows = synthesize_status_from_facilities(tables, facilities)
        print("Adapted legacy shard artifact by creating collection_status.csv.")
    else:
        print("No reusable collection_status.csv or facilities.csv found.")
        write_ids(Path(a.pending_out), expected)
        return 2

    completed = [
        r.get("birth_navi_id", "")
        for r in status_rows
        if r.get("birth_navi_id", "")
    ]
    completed_set = set(completed)

    if len(completed) != len(completed_set):
        print("Prior shard has duplicate collection-status IDs.")
        return 3

    unexpected = sorted(
        completed_set - expected_set,
        key=lambda x: int(x) if x.isdigit() else 10**12,
    )
    if unexpected:
        print(
            "Prior shard is incompatible with the current deterministic shard; "
            f"unexpected completed IDs: {unexpected[:20]}"
        )
        return 4

    # Every table row in the artifact must belong to an ID marked completed.
    for csv_path in sorted(tables.glob("*.csv")):
        if csv_path.name == "collection_status.csv":
            continue
        for row in read_csv(csv_path):
            fid = row.get("birth_navi_id", "")
            if fid and fid not in completed_set:
                print(
                    f"{csv_path.name} contains ID {fid} that is not present in "
                    "collection_status.csv."
                )
                return 5

    pending = [fid for fid in expected if fid not in completed_set]
    write_ids(Path(a.pending_out), pending)

    print(
        f"Prior shard validated: completed={len(completed_set)}, "
        f"pending={len(pending)}, expected={len(expected)}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
