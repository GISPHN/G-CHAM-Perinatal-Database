#!/usr/bin/env python3
from __future__ import annotations
import argparse, csv, json
from datetime import datetime, timezone
from pathlib import Path

TABLES=["collection_status","facilities","facility_detail","delivery","prenatal","prenatal_checkup_details","prenatal_options","pregnancy_checkups","postnatal_services","outpatient_times","external_sites","room_costs","painless_delivery_costs"]
SECONDARY={"prenatal_checkup_details":["period"],"prenatal_options":["checkup_item"],"pregnancy_checkups":["pregnancy_checkup_type"],"postnatal_services":["postnatal_care_type_code"],"outpatient_times":["day_of_week_code"],"external_sites":["external_site_type_code","url"],"room_costs":["room_type_code"],"painless_delivery_costs":["item"]}

def now(): return datetime.now(timezone.utc).isoformat()

def read_many(paths):
    fields=[]; rows=[]; seen=set()
    for p in sorted(paths):
        with p.open("r",encoding="utf-8-sig",newline="") as f:
            r=csv.DictReader(f)
            if not fields and r.fieldnames: fields=list(r.fieldnames)
            for row in r:
                for k in row:
                    if k not in fields: fields.append(k)
                row={k:(v or "") for k,v in row.items()}
                sig=tuple(sorted(row.items()))
                if sig not in seen: rows.append(row); seen.add(sig)
    return fields,rows

def key(table,row):
    try: fid=int(row.get("birth_navi_id",""))
    except: fid=10**12
    return (fid,*[row.get(k,"") for k in SECONDARY.get(table,[])])

def write(path,fields,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore"); w.writeheader(); w.writerows(rows)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--shards-root",required=True); ap.add_argument("--discovery-dir",required=True)
    ap.add_argument("--outdir",required=True); ap.add_argument("--snapshot-year",type=int,required=True)
    ap.add_argument("--parser-version",default="1.0.0")
    a=ap.parse_args(); shards=Path(a.shards_root); disc=Path(a.discovery_dir); out=Path(a.outdir); out.mkdir(parents=True,exist_ok=True)
    counts={}
    for table in TABLES:
        paths=list(shards.glob(f"**/{table}.csv"))
        if not paths: counts[table]=0; continue
        fields,rows=read_many(paths); rows.sort(key=lambda r:key(table,r)); write(out/f"{table}.csv",fields,rows); counts[table]=len(rows)
    for name in ["facility_urls.csv","facility_ids.txt","discovery_metadata.json"]:
        src=disc/name
        if src.exists(): (out/name).write_bytes(src.read_bytes())
    dm=json.loads((disc/"discovery_metadata.json").read_text(encoding="utf-8"))
    meta={"dataset":"G-CHAM Perinatal Database","author":"Ryo Horiike","snapshot_year":a.snapshot_year,"generated_at_utc":now(),"source":"Ministry of Health, Labour and Welfare, Japan - Birth Navi (出産なび)","source_url":"https://birth-navi.mhlw.go.jp/","source_terms_url":"https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/iryou/index_00041.html","parser_version":a.parser_version,"facility_count_from_sitemap":dm.get("facility_count"),"sitemap_retrieved_at_utc":dm.get("retrieved_at_utc"),"table_row_counts":counts,"municipality_dependent_information_included":False}
    (out/"snapshot_metadata.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(meta,ensure_ascii=False,indent=2)); return 0

if __name__=="__main__":
    raise SystemExit(main())
