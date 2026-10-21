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
GSI_REPRESENTATIVE_POINTS = Q / "gsi_address_representative_points.csv"
OUT = Q / "facilities_final_coordinates.csv"
SUMMARY = Q / "coordinate_final_summary.json"

GSI_GRANULARITY_CODES = {
    "街区・番地等": "block_or_address",
    "町字・丁目等": "neighborhood_or_chome",
    "市区町村": "municipality",
    "都道府県": "prefecture",
}


def read_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def write_summary_if_changed(path: Path, summary):
    """Keep the prior generation time when the substantive summary is unchanged."""
    if path.exists():
        try:
            prior = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            prior = None
        if prior:
            prior_body = {k: v for k, v in prior.items() if k != "generated_at_utc"}
            new_body = {k: v for k, v in summary.items() if k != "generated_at_utc"}
            if prior_body == new_body:
                summary["generated_at_utc"] = prior.get(
                    "generated_at_utc", summary["generated_at_utc"]
                )
    path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    verified = read_csv(VERIFIED)
    candidates = read_csv(CANDIDATES)
    manual = read_csv(MANUAL)
    gsi_points = read_csv(GSI_REPRESENTATIVE_POINTS)

    manual_by_id = {r["birth_navi_id"]: r for r in manual}
    if len(manual_by_id) != len(manual):
        raise SystemExit("Duplicate Birth Navi IDs in manual review file.")

    valid_choices = {"birth_navi", "mhlw_iryou_information_net"}
    bad = [r for r in manual if r.get("manual_choice") not in valid_choices]
    if bad:
        raise SystemExit(f"Invalid manual choices: {bad[:5]}")

    gsi_by_id = {r["birth_navi_id"]: r for r in gsi_points}
    if len(gsi_by_id) != len(gsi_points):
        raise SystemExit("Duplicate Birth Navi IDs in GSI representative-point file.")

    verified_ids = {r["birth_navi_id"] for r in verified}
    unknown_gsi_ids = sorted(set(gsi_by_id) - verified_ids, key=int)
    if unknown_gsi_ids:
        raise SystemExit(f"Unknown Birth Navi IDs in GSI file: {unknown_gsi_ids[:10]}")

    for r in gsi_points:
        fid = r["birth_navi_id"]
        granularity = (r.get("representative_point_granularity") or "").strip()
        if granularity not in GSI_GRANULARITY_CODES:
            raise SystemExit(f"Invalid GSI granularity for {fid}: {granularity}")
        try:
            lat = float(r.get("latitude") or "")
            lon = float(r.get("longitude") or "")
        except ValueError as exc:
            raise SystemExit(f"Invalid GSI coordinate for {fid}") from exc
        if not (20 <= lat <= 50 and 120 <= lon <= 155):
            raise SystemExit(f"GSI coordinate outside Japan validation bounds for {fid}")
        required = (
            "gsi_query",
            "gsi_returned_title",
            "coordinate_meaning",
            "retrieved_date_jst",
            "gsi_query_url",
            "address_source_name",
            "address_source_url",
            "coordinate_semantics",
            "source_url",
        )
        missing = [k for k in required if not (r.get(k) or "").strip()]
        if missing:
            raise SystemExit(f"Missing GSI provenance for {fid}: {missing}")

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
    gsi_applied_counts = Counter()
    for r in verified:
        fid = r.get("birth_navi_id", "")
        final_lat = (r.get("verified_latitude") or "").strip()
        final_lon = (r.get("verified_longitude") or "").strip()
        final_source = (r.get("coordinate_source") or "").strip()
        final_status = (r.get("coordinate_quality_status") or "").strip()
        review_status = ""
        reviewed_by = ""
        reviewed_date = ""
        gsi = gsi_by_id.get(fid)
        gsi_applied = "0"

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

        # GSI points fill only records that remain unresolved after direct-source
        # verification and the 44 cross-source manual adjudications. They never
        # replace a Birth Navi or MHLW direct coordinate.
        if gsi:
            if final_lat or final_lon:
                raise SystemExit(
                    f"GSI representative point would overwrite an existing coordinate for {fid}"
                )
            granularity = gsi["representative_point_granularity"].strip()
            granularity_code = GSI_GRANULARITY_CODES[granularity]
            final_lat = gsi["latitude"].strip()
            final_lon = gsi["longitude"].strip()
            final_source = "gsi_maps_address_search"
            final_status = f"gsi_address_representative_point_{granularity_code}"
            gsi_applied = "1"
            gsi_applied_counts[granularity] += 1

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
                "final_coordinate_is_address_representative_point": gsi_applied,
                "gsi_query": gsi.get("gsi_query", "") if gsi else "",
                "gsi_returned_title": gsi.get("gsi_returned_title", "") if gsi else "",
                "gsi_representative_point_granularity": (
                    gsi.get("representative_point_granularity", "") if gsi else ""
                ),
                "gsi_query_strategy": gsi.get("query_strategy", "") if gsi else "",
                "gsi_retrieved_date_jst": gsi.get("retrieved_date_jst", "") if gsi else "",
                "gsi_query_url": gsi.get("gsi_query_url", "") if gsi else "",
                "gsi_address_source_name": gsi.get("address_source_name", "") if gsi else "",
                "gsi_address_source_url": gsi.get("address_source_url", "") if gsi else "",
                "coordinate_location_model": gsi.get("location_model", "") if gsi else "",
                "coordinate_semantics": gsi.get("coordinate_semantics", "") if gsi else "",
                "coordinate_meaning": gsi.get("coordinate_meaning", "") if gsi else "",
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
        "gsi_address_representative_point_count": sum(gsi_applied_counts.values()),
        "gsi_representative_point_granularity_counts": dict(gsi_applied_counts),
        "final_coordinate_present_count": final_present,
        "final_coordinate_missing_count": final_missing,
        "manual_review_file": "data/quality/2026/coordinate_manual_review.csv",
        "gsi_representative_point_file": (
            "data/quality/2026/gsi_address_representative_points.csv"
        ),
        "final_coordinate_file": "data/quality/2026/facilities_final_coordinates.csv",
        "policy": (
            "For the 44 deterministic cross-source discrepancies >500 m, the "
            "manually confirmed source is used. For all other records, the prior "
            "provenance-aware verified coordinate is retained. GSI Maps address "
            "search representative points fill only still-missing coordinates and "
            "are explicitly labelled by result granularity; they are not facility "
            "entrances or building centroids. Original annual snapshot coordinates "
            "remain unchanged."
        ),
    }
    write_summary_if_changed(SUMMARY, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
