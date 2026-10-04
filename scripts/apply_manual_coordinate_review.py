#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
Q = ROOT / "data/quality/2026"

VERIFIED = Q / "facilities_verified_coordinates.csv"
CANDIDATES = Q / "coordinate_verification_candidates.csv"
MANUAL = Q / "coordinate_manual_review.csv"
OUT = Q / "facilities_final_coordinates.csv"
SUMMARY = Q / "coordinate_final_summary.json"


def read_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    verified = read_csv(VERIFIED)
    candidates = read_csv(CANDIDATES)
    manual = read_csv(MANUAL)

    manual_by_id = {r["birth_navi_id"]: r for r in manual}
    if len(manual_by_id) != len(manual):
        raise SystemExit("Duplicate Birth Navi IDs in manual review file.")

    valid_choices = {"birth_navi", "mhlw_iryou_information_net"}
    bad = [r for r in manual if r.get("manual_choice") not in valid_choices]
    if bad:
        raise SystemExit(f"Invalid manual choices: {bad[:5]}")

    # The manual review is specifically for cross-source discrepancies >500 m.
    candidate_by_id = {}
    for r in candidates:
        fid = r.get("birth_navi_id", "")
        d = (r.get("distance_m_if_both") or "").strip()
        if not fid or not d:
            continue
        try:
            if float(d) > 500:
                if fid in candidate_by_id:
                    raise SystemExit(f"Multiple >500 m candidates for Birth Navi ID {fid}")
                candidate_by_id[fid] = r
        except ValueError:
            continue

    missing_manual = sorted(set(candidate_by_id) - set(manual_by_id), key=int)
    unexpected_manual = sorted(set(manual_by_id) - set(candidate_by_id), key=int)
    if missing_manual or unexpected_manual:
        raise SystemExit(
            f"Manual review/candidate mismatch. missing_manual={missing_manual}, "
            f"unexpected_manual={unexpected_manual}"
        )

    out_rows = []
    review_counts = Counter()
    for r in verified:
        fid = r.get("birth_navi_id", "")
        final_lat = (r.get("verified_latitude") or "").strip()
        final_lon = (r.get("verified_longitude") or "").strip()
        final_source = (r.get("coordinate_source") or "").strip()
        final_status = (r.get("coordinate_quality_status") or "").strip()
        review_status = ""
        reviewed_by = ""
        reviewed_date = ""

        if fid in manual_by_id:
            m = manual_by_id[fid]
            c = candidate_by_id[fid]
            choice = m["manual_choice"]

            if choice == "birth_navi":
                final_lat = (c.get("birth_navi_latitude") or "").strip()
                final_lon = (c.get("birth_navi_longitude") or "").strip()
                final_source = "birth_navi_manual_confirmation"
                final_status = "manual_confirmed_birth_navi"
            else:
                final_lat = (c.get("official_latitude") or "").strip()
                final_lon = (c.get("official_longitude") or "").strip()
                final_source = "mhlw_iryou_information_net_manual_confirmation"
                final_status = "manual_confirmed_mhlw_iryou_information_net"

            if not final_lat or not final_lon:
                raise SystemExit(f"Selected manual coordinate is blank for {fid}")

            review_status = "confirmed"
            reviewed_by = m.get("reviewed_by", "")
            reviewed_date = m.get("reviewed_date", "")
            review_counts[choice] += 1

        x = dict(r)
        x.update(
            {
                "final_latitude": final_lat,
                "final_longitude": final_lon,
                "final_coordinate_source": final_source,
                "final_coordinate_status": final_status,
                "manual_review_status": review_status,
                "manual_reviewed_by": reviewed_by,
                "manual_review_date": reviewed_date,
            }
        )
        out_rows.append(x)

    if not out_rows:
        raise SystemExit("No verified-coordinate rows found.")

    fields = list(out_rows[0].keys())
    write_csv(OUT, out_rows, fields)

    final_present = sum(
        bool((r.get("final_latitude") or "").strip())
        and bool((r.get("final_longitude") or "").strip())
        for r in out_rows
    )
    final_missing = len(out_rows) - final_present

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "snapshot_year": 2026,
        "facility_count": len(out_rows),
        "manual_discrepancy_reviews": len(manual),
        "manual_choice_birth_navi": review_counts["birth_navi"],
        "manual_choice_mhlw_iryou_information_net": review_counts[
            "mhlw_iryou_information_net"
        ],
        "final_coordinate_present_count": final_present,
        "final_coordinate_missing_count": final_missing,
        "manual_review_file": "data/quality/2026/coordinate_manual_review.csv",
        "final_coordinate_file": "data/quality/2026/facilities_final_coordinates.csv",
        "policy": (
            "For the 44 deterministic cross-source discrepancies >500 m, the "
            "manually confirmed source is used. For all other records, the prior "
            "provenance-aware verified coordinate is retained. Original annual "
            "snapshot coordinates remain unchanged."
        ),
    }
    SUMMARY.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
