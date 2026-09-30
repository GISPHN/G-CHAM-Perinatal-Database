#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,json
from datetime import datetime,timezone
from pathlib import Path

def rows(path):
    if not path.exists(): return []
    with path.open("r",encoding="utf-8-sig",newline="") as f: return list(csv.DictReader(f))

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--snapshot-dir",required=True); a=ap.parse_args(); root=Path(a.snapshot_dir)
    expected=[x.strip() for x in (root/"facility_ids.txt").read_text(encoding="utf-8-sig").splitlines() if x.strip()]
    fac=rows(root/"facilities.csv"); actual=[r.get("birth_navi_id","") for r in fac]
    es,aset=set(expected),set(actual); dup=len(actual)!=len(aset)
    miss=sorted(es-aset,key=int); extra=sorted(aset-es,key=lambda x:int(x) if x.isdigit() else 10**12)
    invalid=missing_coord=missing_name=hidden_addr=hidden_phone=0; patterns={}
    for r in fac:
        if not (r.get("facility_name") or "").strip(): missing_name+=1
        lat=(r.get("latitude") or "").strip(); lon=(r.get("longitude") or "").strip()
        if not lat or not lon: missing_coord+=1
        else:
            try:
                la,lo=float(lat),float(lon)
                if not (20<=la<=50 and 120<=lo<=155): invalid+=1
            except: invalid+=1
        if (r.get("is_address_visible") or "").lower()=="false" and (r.get("address") or "").strip(): hidden_addr+=1
        if (r.get("is_phone_number_visible") or "").lower()=="false" and (r.get("phone_number") or "").strip(): hidden_phone+=1
        p=r.get("service_pattern") or ""; patterns[p]=patterns.get(p,0)+1
    s={"generated_at_utc":datetime.now(timezone.utc).isoformat(),"expected_facility_count":len(expected),"actual_facility_count":len(actual),"complete":es==aset and not dup,"duplicate_ids":dup,"missing_id_count":len(miss),"unexpected_id_count":len(extra),"missing_name_count":missing_name,"missing_coordinate_count":missing_coord,"invalid_coordinate_count":invalid,"hidden_address_violation_count":hidden_addr,"hidden_phone_violation_count":hidden_phone,"service_pattern_counts":patterns,"missing_ids_sample":miss[:20],"unexpected_ids_sample":extra[:20]}
    (root/"validation_summary.json").write_text(json.dumps(s,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(s,ensure_ascii=False,indent=2))
    return 2 if (not s["complete"] or invalid or hidden_addr or hidden_phone or missing_name) else 0

if __name__=="__main__":
    raise SystemExit(main())
