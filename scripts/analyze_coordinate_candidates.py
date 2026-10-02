#!/usr/bin/env python3
from __future__ import annotations
import csv, json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
Q=ROOT/"data/quality/2026"
SNAP=ROOT/"data/snapshots/2026"

def read(path):
    with path.open("r",encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f))

def write(path, rows, fields):
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore"); w.writeheader(); w.writerows(rows)

def main():
    fac={r["birth_navi_id"]:r for r in read(SNAP/"facilities.csv")}
    cand=read(Q/"coordinate_verification_candidates.csv")
    prefix=[]
    discrep=[]
    for r in cand:
        b=fac.get(r["birth_navi_id"],{})
        if r.get("match_class")=="candidate_exact_name_pref_municipality_address_prefix" and not (r.get("birth_navi_latitude") or ""):
            code=b.get("facility_type_code","")
            expected={"1":"hospital","2":"clinic","3":"clinic","4":"maternity_home","5":"maternity_home"}.get(code)
            x=dict(r)
            x.update({"facility_type_code":code,"facility_type":b.get("facility_type",""),"service_pattern":b.get("service_pattern",""),"type_source_compatible":str(expected==r.get("official_source")).lower() if expected else "false"})
            prefix.append(x)
        d=(r.get("distance_m_if_both") or "").strip()
        if d:
            try:
                if float(d)>500:
                    x=dict(r); x.update({"facility_type_code":b.get("facility_type_code",""),"facility_type":b.get("facility_type",""),"service_pattern":b.get("service_pattern","")})
                    discrep.append(x)
            except ValueError: pass
    compatible=[r for r in prefix if r["type_source_compatible"]=="true"]
    summary={
      "generated_at_utc":datetime.now(timezone.utc).isoformat(),
      "missing_coordinate_prefix_candidates":len(prefix),
      "prefix_candidates_by_facility_type":dict(Counter(r["facility_type"] or "(blank)" for r in prefix).most_common()),
      "prefix_candidates_by_service_pattern":dict(Counter(r["service_pattern"] or "(blank)" for r in prefix).most_common()),
      "type_source_compatible_prefix_candidates":len(compatible),
      "type_source_compatible_ids":[r["birth_navi_id"] for r in compatible],
      "cross_source_discrepancies_over_500m":len(discrep),
      "cross_source_discrepancies_over_1000m":sum(float(r["distance_m_if_both"])>1000 for r in discrep),
      "largest_discrepancies":[
        {"birth_navi_id":r["birth_navi_id"],"facility_name":r["facility_name"],"distance_m":float(r["distance_m_if_both"]),"birth_navi_address":r["birth_navi_address"],"official_address":r["official_address"]}
        for r in sorted(discrep,key=lambda x:float(x["distance_m_if_both"]),reverse=True)[:30]
      ]
    }
    fields=list(prefix[0].keys()) if prefix else ["birth_navi_id"]
    write(Q/"coordinate_prefix_candidates.csv",prefix,fields)
    fields2=list(discrep[0].keys()) if discrep else ["birth_navi_id"]
    write(Q/"coordinate_discrepancies_over_500m.csv",discrep,fields2)
    (Q/"coordinate_candidate_analysis.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
