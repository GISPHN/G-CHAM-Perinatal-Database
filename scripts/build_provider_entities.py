#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAP = ROOT / "data/snapshots/2026"
QUALITY = ROOT / "data/quality/2026"
OUT = ROOT / "data/derived/2026"

FACILITIES = QUALITY / "facilities_final_coordinates.csv"
POSTNATAL = SNAP / "postnatal_services.csv"

LEGAL_TERMS = (
    "地方独立行政法人",
    "独立行政法人",
    "国立大学法人",
    "公立大学法人",
    "社会福祉法人",
    "公益財団法人",
    "一般財団法人",
    "公益社団法人",
    "一般社団法人",
    "医療法人社団",
    "医療法人財団",
    "医療法人",
    "財団法人",
    "社団法人",
)

GENERIC_NAMES = {
    "個人助産師",
    "個人事業主助産師",
    "在宅助産師",
    "出張専業助産師",
    "助産師",
}

TYPE_LABEL = {
    "1": "病院",
    "2": "有床診療所",
    "3": "無床診療所",
    "4": "有床助産所",
    "5": "無床助産所",
    "100": "自治体連携等の産後ケア掲載レコード",
}


def read_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def norm_text(value: str) -> str:
    s = unicodedata.normalize("NFKC", value or "").lower()
    s = s.translate(str.maketrans({
        "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-", "−": "-",
    }))
    return "".join(
        ch for ch in s
        if not ch.isspace() and unicodedata.category(ch)[0] not in {"P", "S"}
    )


def canonical_name(value: str) -> str:
    s = unicodedata.normalize("NFKC", value or "")
    for term in LEGAL_TERMS:
        s = s.replace(term, "")
    return norm_text(s)


def norm_phone(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def norm_address(value: str) -> str:
    return norm_text(value)


def to_float(value):
    try:
        return float(value)
    except Exception:
        return None


def haversine_m(lat1, lon1, lat2, lon2):
    vals = [to_float(x) for x in (lat1, lon1, lat2, lon2)]
    if any(v is None for v in vals):
        return None
    lat1, lon1, lat2, lon2 = vals
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class DSU:
    def __init__(self, ids):
        self.parent = {x: x for x in ids}
        self.rank = {x: 0 for x in ids}

    def find(self, x):
        p = self.parent[x]
        if p != x:
            self.parent[x] = self.find(p)
        return self.parent[x]

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1
        return True


def coord_of(r):
    lat = (r.get("final_latitude") or "").strip()
    lon = (r.get("final_longitude") or "").strip()
    if lat and lon:
        return lat, lon
    return None


def informative(r):
    return bool(
        norm_phone(r.get("phone_number", ""))
        or norm_address(r.get("address", ""))
        or coord_of(r)
        or (r.get("coordinate_source_id") or "").strip()
    )


def pair_far_apart(a, b, threshold=1000.0):
    ca, cb = coord_of(a), coord_of(b)
    if not ca or not cb:
        return False
    d = haversine_m(ca[0], ca[1], cb[0], cb[1])
    return d is not None and d > threshold


def choose_representative(rows):
    def score(r):
        type_code = str(r.get("facility_type_code") or "")
        standard = type_code in {"1", "2", "3", "4", "5"}
        return (
            1 if standard else 0,
            1 if coord_of(r) else 0,
            1 if (r.get("address") or "").strip() else 0,
            1 if norm_phone(r.get("phone_number", "")) else 0,
            -int(r.get("birth_navi_id") or 999999999),
        )
    return max(rows, key=score)


def stable_provider_id(rows):
    min_id = min(int(r["birth_navi_id"]) for r in rows)
    return f"GCP-{min_id:05d}"


def unique_nonblank(rows, key):
    return sorted({(r.get(key) or "").strip() for r in rows if (r.get(key) or "").strip()})


def main() -> int:
    rows = read_csv(FACILITIES)
    by_id = {r["birth_navi_id"]: r for r in rows}
    ids = list(by_id)
    dsu = DSU(ids)
    edge_methods = defaultdict(list)

    # Precompute normalized fields.
    for r in rows:
        r["_name"] = norm_text(r.get("facility_name", ""))
        r["_cname"] = canonical_name(r.get("facility_name", ""))
        r["_phone"] = norm_phone(r.get("phone_number", ""))
        r["_addr"] = norm_address(r.get("address", ""))
        r["_source_id"] = (r.get("coordinate_source_id") or "").strip()

    def link(a, b, method):
        if a["birth_navi_id"] == b["birth_navi_id"]:
            return
        if pair_far_apart(a, b) and method not in {"same_official_source_id"}:
            return
        if dsu.union(a["birth_navi_id"], b["birth_navi_id"]):
            edge_methods[a["birth_navi_id"]].append(method)
            edge_methods[b["birth_navi_id"]].append(method)

    # 1) Strongest identifier: same non-empty official source entity ID.
    by_source_id = defaultdict(list)
    for r in rows:
        if r["_source_id"]:
            by_source_id[r["_source_id"]].append(r)
    for group in by_source_id.values():
        if len(group) < 2:
            continue
        base = group[0]
        for other in group[1:]:
            link(base, other, "same_official_source_id")

    # 2) Exact canonical name + exact visible/public address.
    by_name_addr = defaultdict(list)
    for r in rows:
        if r["_cname"] and r["_addr"]:
            by_name_addr[(r["_cname"], r["_addr"])].append(r)
    for group in by_name_addr.values():
        if len(group) < 2:
            continue
        base = group[0]
        for other in group[1:]:
            link(base, other, "same_name_exact_address")

    # 3) Exact canonical name + exact public phone.
    by_name_phone = defaultdict(list)
    for r in rows:
        if r["_cname"] and r["_phone"]:
            by_name_phone[(r["_cname"], r["_phone"])].append(r)
    for group in by_name_phone.values():
        if len(group) < 2:
            continue
        base = group[0]
        for other in group[1:]:
            link(base, other, "same_name_exact_phone")

    # 4) Exact canonical name + very close coordinates (<=100 m).
    by_cname = defaultdict(list)
    for r in rows:
        if r["_cname"]:
            by_cname[r["_cname"]].append(r)
    for group in by_cname.values():
        with_coord = [r for r in group if coord_of(r)]
        for i in range(len(with_coord)):
            for j in range(i + 1, len(with_coord)):
                a, b = with_coord[i], with_coord[j]
                ca, cb = coord_of(a), coord_of(b)
                d = haversine_m(ca[0], ca[1], cb[0], cb[1])
                if d is not None and d <= 100:
                    link(a, b, "same_name_coordinate_within_100m")

    # 5) Conservative name-only propagation for type-100 listings.
    # This is allowed only when the exact surface-name group has a single evidence
    # cluster and no conflicting informative record. Generic labels never propagate.
    by_exact_name = defaultdict(list)
    for r in rows:
        if r["_name"]:
            by_exact_name[r["_name"]].append(r)

    propagation_method = {}
    for _, group in by_exact_name.items():
        if len(group) < 2:
            continue
        display_names = {r.get("facility_name", "").strip() for r in group}
        display_name = next(iter(display_names)) if display_names else ""
        if display_name in GENERIC_NAMES:
            continue

        info = [r for r in group if informative(r)]
        if not info:
            continue

        roots = {dsu.find(r["birth_navi_id"]) for r in info}
        standard_roots = {
            dsu.find(r["birth_navi_id"])
            for r in info
            if str(r.get("facility_type_code") or "") in {"1", "2", "3", "4", "5"}
        }

        target_root = None
        method = None

        # If one unique standard-facility entity exists, use it as anchor unless
        # another informative record forms a conflicting evidence cluster.
        if len(standard_roots) == 1 and len(roots) == 1:
            target_root = next(iter(roots))
            method = "name_only_to_unique_standard_anchor"
        elif len(roots) == 1:
            target_root = next(iter(roots))
            method = "name_only_single_evidence_cluster"

        if target_root is None:
            continue

        anchor_id = next(r["birth_navi_id"] for r in info if dsu.find(r["birth_navi_id"]) == target_root)
        anchor = by_id[anchor_id]

        for r in group:
            if informative(r):
                continue
            if str(r.get("facility_type_code") or "") != "100":
                continue
            if link(anchor, r, method) is None:
                # link() returns None; record method after union/root check below.
                pass
            if dsu.find(r["birth_navi_id"]) == dsu.find(anchor_id):
                propagation_method[r["birth_navi_id"]] = method

    # Materialize components.
    components = defaultdict(list)
    for r in rows:
        components[dsu.find(r["birth_navi_id"])].append(r)

    provider_rows = []
    listing_rows = []
    component_provider_id = {}

    for comp_rows in components.values():
        pid = stable_provider_id(comp_rows)
        for r in comp_rows:
            component_provider_id[r["birth_navi_id"]] = pid

        rep = choose_representative(comp_rows)
        coords = []
        for r in comp_rows:
            c = coord_of(r)
            if c:
                coords.append((float(c[0]), float(c[1]), r))
        coord_conflict = 0
        max_coord_spread = 0.0
        for i in range(len(coords)):
            for j in range(i + 1, len(coords)):
                d = haversine_m(coords[i][0], coords[i][1], coords[j][0], coords[j][1]) or 0.0
                max_coord_spread = max(max_coord_spread, d)
        if max_coord_spread > 500:
            coord_conflict = 1

        standard = [r for r in comp_rows if str(r.get("facility_type_code") or "") in {"1","2","3","4","5"}]
        type100 = [r for r in comp_rows if str(r.get("facility_type_code") or "") == "100"]

        rep_coord = coord_of(rep)
        provider_rows.append({
            "provider_id": pid,
            "provider_name": rep.get("facility_name", ""),
            "provider_name_canonical": rep.get("_cname", ""),
            "provider_type_code": rep.get("facility_type_code", ""),
            "provider_type": TYPE_LABEL.get(str(rep.get("facility_type_code") or ""), rep.get("facility_type", "")),
            "representative_birth_navi_id": rep.get("birth_navi_id", ""),
            "listing_count": len(comp_rows),
            "standard_facility_listing_count": len(standard),
            "municipality_linked_type100_listing_count": len(type100),
            "birth_navi_ids": ";".join(sorted((r["birth_navi_id"] for r in comp_rows), key=int)),
            "public_address": rep.get("address", ""),
            "public_phone_number": rep.get("phone_number", ""),
            "latitude": rep_coord[0] if rep_coord else "",
            "longitude": rep_coord[1] if rep_coord else "",
            "coordinate_source": rep.get("final_coordinate_source", ""),
            "coordinate_status": rep.get("final_coordinate_status", ""),
            "coordinate_conflict_over_500m": coord_conflict,
            "max_coordinate_spread_m": f"{max_coord_spread:.1f}" if coords else "",
            "prenatal_checkup_listed_any": int(any(r.get("prenatal_checkup_listed") == "1" for r in comp_rows)),
            "delivery_listed_any": int(any(r.get("delivery_listed") == "1" for r in comp_rows)),
            "postnatal_care_listed_any": int(any(r.get("postnatal_care_listed") == "1" for r in comp_rows)),
            "source_entity_ids": ";".join(unique_nonblank(comp_rows, "coordinate_source_id")),
        })

    # Listing map with an explicit statement that birth_navi_id is a listing ID.
    for r in sorted(rows, key=lambda x: int(x["birth_navi_id"])):
        pid = component_provider_id[r["birth_navi_id"]]
        comp = next(v for v in components.values() if component_provider_id[v[0]["birth_navi_id"]] == pid)
        methods = set(edge_methods.get(r["birth_navi_id"], []))
        if r["birth_navi_id"] in propagation_method:
            methods.add(propagation_method[r["birth_navi_id"]])
        if len(comp) == 1:
            method = "singleton_no_deduplication"
            confidence = "not_applicable"
        elif "same_official_source_id" in methods:
            method = "same_official_source_id"
            confidence = "high"
        elif "same_name_exact_address" in methods:
            method = "same_name_exact_address"
            confidence = "high"
        elif "same_name_exact_phone" in methods:
            method = "same_name_exact_phone"
            confidence = "high"
        elif "same_name_coordinate_within_100m" in methods:
            method = "same_name_coordinate_within_100m"
            confidence = "high"
        elif r["birth_navi_id"] in propagation_method:
            method = propagation_method[r["birth_navi_id"]]
            confidence = "medium"
        else:
            method = "connected_by_other_cluster_member"
            confidence = "high"

        listing_rows.append({
            "birth_navi_id": r["birth_navi_id"],
            "provider_id": pid,
            "facility_name": r.get("facility_name", ""),
            "facility_type_code": r.get("facility_type_code", ""),
            "listing_role": "municipality_linked_postnatal_listing" if str(r.get("facility_type_code") or "") == "100" else "facility_listing",
            "listing_municipality_code": r.get("municipality_code", ""),
            "listing_municipality_name": r.get("municipality_name", ""),
            "listing_address": r.get("address", ""),
            "listing_phone_number": r.get("phone_number", ""),
            "deduplication_method": method,
            "deduplication_confidence": confidence,
            "source_url": r.get("source_url", ""),
        })

    # Municipality-provider relation table for every postnatal listing.
    postnatal_rows = read_csv(POSTNATAL)
    services_by_id = defaultdict(list)
    for r in postnatal_rows:
        services_by_id[r.get("birth_navi_id", "")].append(r)

    rel_rows = []
    for r in rows:
        if r.get("postnatal_care_listed") != "1" and r["birth_navi_id"] not in services_by_id:
            continue
        service_rows = services_by_id.get(r["birth_navi_id"], [])
        codes = sorted({x.get("postnatal_care_type_code", "") for x in service_rows if x.get("postnatal_care_type_code", "")})
        labels = sorted({x.get("postnatal_care_type", "") for x in service_rows if x.get("postnatal_care_type", "")})
        rel_rows.append({
            "provider_id": component_provider_id[r["birth_navi_id"]],
            "birth_navi_id": r["birth_navi_id"],
            "listing_role": "municipality_linked_postnatal_listing" if str(r.get("facility_type_code") or "") == "100" else "facility_listing",
            "municipality_code": r.get("municipality_code", ""),
            "municipality_name": r.get("municipality_name", ""),
            "postnatal_care_type_codes": ";".join(codes),
            "postnatal_care_type_labels": ";".join(labels),
            "source_url": r.get("source_url", ""),
        })

    # Review file: same exact name maps to multiple provider entities.
    provider_by_listing = component_provider_id
    review_rows = []
    for name_key, group in by_exact_name.items():
        if len(group) < 2:
            continue
        pids = sorted({provider_by_listing[r["birth_navi_id"]] for r in group})
        if len(pids) <= 1:
            continue
        display_name = group[0].get("facility_name", "")
        review_rows.append({
            "facility_name": display_name,
            "normalized_name": name_key,
            "listing_count": len(group),
            "provider_entity_count": len(pids),
            "provider_ids": ";".join(pids),
            "birth_navi_ids": ";".join(sorted((r["birth_navi_id"] for r in group), key=int)),
            "municipality_codes": ";".join(sorted({r.get("municipality_code", "") for r in group if r.get("municipality_code", "")})),
            "addresses": " || ".join(sorted({r.get("address", "") for r in group if r.get("address", "")})),
            "phones": ";".join(sorted({norm_phone(r.get("phone_number", "")) for r in group if norm_phone(r.get("phone_number", ""))})),
            "review_reason": "same_name_multiple_provider_entities_not_automatically_merged",
        })

    provider_rows.sort(key=lambda r: int(r["representative_birth_navi_id"]))
    rel_rows.sort(key=lambda r: (r["provider_id"], r["municipality_code"], int(r["birth_navi_id"])))
    review_rows.sort(key=lambda r: (-int(r["listing_count"]), r["facility_name"]))

    OUT.mkdir(parents=True, exist_ok=True)
    write_csv(OUT / "providers.csv", provider_rows, [
        "provider_id","provider_name","provider_name_canonical","provider_type_code","provider_type",
        "representative_birth_navi_id","listing_count","standard_facility_listing_count",
        "municipality_linked_type100_listing_count","birth_navi_ids","public_address",
        "public_phone_number","latitude","longitude","coordinate_source","coordinate_status",
        "coordinate_conflict_over_500m","max_coordinate_spread_m",
        "prenatal_checkup_listed_any","delivery_listed_any","postnatal_care_listed_any",
        "source_entity_ids",
    ])
    write_csv(OUT / "provider_listing_map.csv", listing_rows, [
        "birth_navi_id","provider_id","facility_name","facility_type_code","listing_role",
        "listing_municipality_code","listing_municipality_name","listing_address",
        "listing_phone_number","deduplication_method","deduplication_confidence","source_url",
    ])
    write_csv(OUT / "municipality_postnatal_services.csv", rel_rows, [
        "provider_id","birth_navi_id","listing_role","municipality_code","municipality_name",
        "postnatal_care_type_codes","postnatal_care_type_labels","source_url",
    ])
    write_csv(OUT / "deduplication_review.csv", review_rows, [
        "facility_name","normalized_name","listing_count","provider_entity_count",
        "provider_ids","birth_navi_ids","municipality_codes","addresses","phones","review_reason",
    ])

    cluster_sizes = Counter(int(r["listing_count"]) for r in provider_rows)
    methods = Counter(r["deduplication_method"] for r in listing_rows)
    confidence = Counter(r["deduplication_confidence"] for r in listing_rows)

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "snapshot_year": 2026,
        "source_birth_navi_listing_count": len(rows),
        "derived_provider_entity_count": len(provider_rows),
        "listings_collapsed_relative_to_one_row_per_listing": len(rows) - len(provider_rows),
        "multi_listing_provider_count": sum(1 for r in provider_rows if int(r["listing_count"]) > 1),
        "largest_provider_listing_count": max((int(r["listing_count"]) for r in provider_rows), default=0),
        "type100_listing_count": sum(str(r.get("facility_type_code") or "") == "100" for r in rows),
        "postnatal_municipality_relation_rows": len(rel_rows),
        "same_name_groups_left_as_multiple_provider_entities": len(review_rows),
        "deduplication_method_counts": dict(methods),
        "deduplication_confidence_counts": dict(confidence),
        "provider_cluster_size_distribution": {str(k): v for k, v in sorted(cluster_sizes.items())},
        "principles": [
            "birth_navi_id is treated as a source listing ID, not a physical-provider ID",
            "raw annual snapshot is never overwritten",
            "same name alone is insufficient for automatic merging except conservative propagation of identifier-empty type-100 listings into one unambiguous evidence cluster",
            "generic names are never merged by name-only propagation",
            "coordinates farther than 1 km prevent phone/address/name-based linking unless the same official source entity ID is present",
            "ambiguous same-name groups remain separate and are exported for manual review",
        ],
    }
    (OUT / "deduplication_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
