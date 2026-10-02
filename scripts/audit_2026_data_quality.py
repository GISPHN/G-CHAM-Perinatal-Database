#!/usr/bin/env python3
from __future__ import annotations
import csv, json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SNAP=ROOT/"data/snapshots/2026"
OUT=ROOT/"data/quality/2026"

def read_csv(path):
    with path.open("r",encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f))

def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore"); w.writeheader(); w.writerows(rows)

def cdict(rows,key):
    return dict(Counter((r.get(key) or "(blank)") for r in rows).most_common())

def main():
    rows=read_csv(SNAP/"facilities.csv")
    missing=[r for r in rows if not (r.get("latitude") or "").strip() or not (r.get("longitude") or "").strip()]
    none=[r for r in rows if (r.get("service_pattern") or "")=="none"]
    overlap=[r for r in missing if (r.get("service_pattern") or "")=="none"]

    fields=["birth_navi_id","facility_name","facility_type_code","facility_type","prefecture_id","municipality_code","municipality_name","address","is_address_visible","phone_number","is_phone_number_visible","latitude","longitude","prenatal_checkup_listed","delivery_listed","postnatal_care_listed","service_count","service_pattern","source_last_modified_at","source_url"]
    write_csv(OUT/"missing_coordinates.csv",missing,fields)
    write_csv(OUT/"service_pattern_none.csv",none,fields)

    summary={
      "generated_at_utc":datetime.now(timezone.utc).isoformat(),
      "snapshot_year":2026,
      "retrievable_facility_count":len(rows),
      "missing_coordinate_count":len(missing),
      "missing_coordinate_percent":round(len(missing)/len(rows)*100,2),
      "service_pattern_none_count":len(none),
      "service_pattern_none_percent":round(len(none)/len(rows)*100,2),
      "missing_coordinate_and_none_overlap":len(overlap),
      "missing_coordinates":{
        "by_facility_type":cdict(missing,"facility_type"),
        "by_service_pattern":cdict(missing,"service_pattern"),
        "by_prefecture_id":cdict(missing,"prefecture_id"),
        "address_present":sum(bool((r.get("address") or "").strip()) for r in missing),
        "address_visible_false":sum((r.get("is_address_visible") or "").lower()=="false" for r in missing),
        "phone_present":sum(bool((r.get("phone_number") or "").strip()) for r in missing),
      },
      "service_pattern_none":{
        "by_facility_type":cdict(none,"facility_type"),
        "by_prefecture_id":cdict(none,"prefecture_id"),
        "coordinate_present":sum(bool((r.get("latitude") or "").strip()) and bool((r.get("longitude") or "").strip()) for r in none),
        "coordinate_missing":sum(not (r.get("latitude") or "").strip() or not (r.get("longitude") or "").strip() for r in none),
        "address_present":sum(bool((r.get("address") or "").strip()) for r in none),
      }
    }
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/"audit_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
