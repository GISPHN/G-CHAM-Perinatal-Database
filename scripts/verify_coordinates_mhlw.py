#!/usr/bin/env python3
from __future__ import annotations
import csv, io, json, math, re, unicodedata, urllib.request, zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SNAP=ROOT/"data/snapshots/2026"
OUT=ROOT/"data/quality/2026"

SOURCES={
 "hospital":"https://www.mhlw.go.jp/content/11121000/01-1_hospital_facility_info_20260601.csv.zip",
 "clinic":"https://www.mhlw.go.jp/content/11121000/02-1_clinic_facility_info_20260601.csv.zip",
 "maternity_home":"https://www.mhlw.go.jp/content/11121000/04_maternity_home_20260601.csv.zip",
}
SOURCE_DATE="2026-06-01"

def read_csv(path):
    with path.open("r",encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f))

def write_csv(path,rows,fields):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore"); w.writeheader(); w.writerows(rows)

def norm(s):
    s=unicodedata.normalize("NFKC",s or "").lower()
    s=s.translate(str.maketrans({"‐":"-","‑":"-","‒":"-","–":"-","—":"-","―":"-","ー":"-","−":"-"}))
    return "".join(ch for ch in s if not ch.isspace() and unicodedata.category(ch)[0] not in {"P","S"})

def load_official():
    allrows=[]
    for kind,url in SOURCES.items():
        req=urllib.request.Request(url,headers={"User-Agent":"G-CHAM-Perinatal-Database/1.0 (+https://github.com/GISPHN/G-CHAM-Perinatal-Database)"})
        with urllib.request.urlopen(req,timeout=90) as r:
            raw=r.read()
        z=zipfile.ZipFile(io.BytesIO(raw))
        for name in z.namelist():
            if not name.lower().endswith(".csv"): continue
            data=z.read(name).decode("utf-8-sig")
            for r in csv.DictReader(io.StringIO(data)):
                lat=(r.get("所在地座標（緯度）") or "").strip(); lon=(r.get("所在地座標（経度）") or "").strip()
                try:
                    la=float(lat); lo=float(lon)
                    valid=20<=la<=50 and 120<=lo<=155
                except Exception:
                    valid=False
                if not valid: continue
                pref=(r.get("都道府県コード") or "").zfill(2)
                muni=(r.get("市区町村コード") or "").zfill(3)
                allrows.append({
                    "official_source":kind,"official_id":r.get("ID",""),"official_name":r.get("正式名称",""),
                    "official_address":r.get("所在地",""),"official_latitude":lat,"official_longitude":lon,
                    "official_prefecture_code":pref,"official_municipality_code":muni,
                    "official_homepage":r.get("案内用ホームページアドレス",""),
                    "_name":norm(r.get("正式名称","")),"_addr":norm(r.get("所在地",""))
                })
    return allrows

def haversine(lat1,lon1,lat2,lon2):
    r=6371008.8
    p1,p2=math.radians(lat1),math.radians(lat2)
    dp=math.radians(lat2-lat1); dl=math.radians(lon2-lon1)
    a=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*r*math.asin(math.sqrt(a))

def main():
    birth=read_csv(SNAP/"facilities.csv")
    official=load_official()
    idx=defaultdict(list)
    for o in official:
        idx[(o["_name"],o["official_prefecture_code"],o["official_municipality_code"])].append(o)

    candidates=[]; derived=[]; exact_fills=0; prefix_candidates=0; ambiguous=0
    verified_existing=0; discrepancies_100=discrepancies_500=discrepancies_1000=0

    for b in birth:
        pref=str(b.get("prefecture_id") or "").zfill(2)
        muni_full=str(b.get("municipality_code") or "")
        muni=muni_full[-3:].zfill(3) if muni_full else ""
        visible=(b.get("is_address_visible") or "").lower()!="false"
        addr=(b.get("address") or "").strip()
        bn=norm(b.get("facility_name","")); ba=norm(addr)
        matches=idx.get((bn,pref,muni),[])
        exact=[o for o in matches if ba and o["_addr"]==ba]
        prefix=[o for o in matches if ba and o["_addr"]!=ba and (o["_addr"].startswith(ba) or ba.startswith(o["_addr"])) and min(len(ba),len(o["_addr"]))>=8]
        chosen=None; method=""
        if visible and len(exact)==1:
            chosen=exact[0]; method="exact_name_pref_municipality_address"
        elif visible and len(exact)==0 and len(matches)==1 and len(prefix)==1:
            method="candidate_exact_name_pref_municipality_address_prefix"
            prefix_candidates+=1
        elif visible and len(matches)>1:
            ambiguous+=1

        orig_lat=(b.get("latitude") or "").strip(); orig_lon=(b.get("longitude") or "").strip()
        final_lat=orig_lat; final_lon=orig_lon
        coord_source="birth_navi" if orig_lat and orig_lon else ""
        source_id=""; source_date=""; match_method=""
        if chosen:
            source_id=chosen["official_id"]; source_date=SOURCE_DATE; match_method=method
            if not orig_lat or not orig_lon:
                final_lat=chosen["official_latitude"]; final_lon=chosen["official_longitude"]
                coord_source="mhlw_iryou_information_net_open_data"
                exact_fills+=1
            else:
                verified_existing+=1

        dist=""
        if chosen and orig_lat and orig_lon:
            try:
                d=haversine(float(orig_lat),float(orig_lon),float(chosen["official_latitude"]),float(chosen["official_longitude"]))
                dist=f"{d:.1f}"
                if d>100: discrepancies_100+=1
                if d>500: discrepancies_500+=1
                if d>1000: discrepancies_1000+=1
            except Exception: pass

        if visible and (exact or prefix or (matches and not chosen)):
            pool=exact if exact else prefix if prefix else matches
            for o in pool:
                candidates.append({
                    "birth_navi_id":b.get("birth_navi_id"),"facility_name":b.get("facility_name"),"birth_navi_address":addr,
                    "birth_navi_latitude":orig_lat,"birth_navi_longitude":orig_lon,
                    "match_class":method or ("ambiguous_name_municipality" if len(matches)>1 else "name_municipality_only"),
                    "official_source":o["official_source"],"official_id":o["official_id"],"official_name":o["official_name"],
                    "official_address":o["official_address"],"official_latitude":o["official_latitude"],"official_longitude":o["official_longitude"],
                    "official_source_date":SOURCE_DATE,"distance_m_if_both":dist if chosen and o["official_id"]==chosen["official_id"] else ""
                })

        drow=dict(b)
        drow.update({
            "verified_latitude":final_lat,"verified_longitude":final_lon,
            "coordinate_source":coord_source,
            "coordinate_source_id":source_id,
            "coordinate_source_date":source_date,
            "coordinate_match_method":match_method,
            "coordinate_crosscheck_distance_m":dist,
            "coordinate_privacy_note":"not_inferred_from_hidden_address" if not visible and (not orig_lat or not orig_lon) else ""
        })
        derived.append(drow)

    cand_fields=["birth_navi_id","facility_name","birth_navi_address","birth_navi_latitude","birth_navi_longitude","match_class","official_source","official_id","official_name","official_address","official_latitude","official_longitude","official_source_date","distance_m_if_both"]
    write_csv(OUT/"coordinate_verification_candidates.csv",candidates,cand_fields)
    fields=list(birth[0].keys())+["verified_latitude","verified_longitude","coordinate_source","coordinate_source_id","coordinate_source_date","coordinate_match_method","coordinate_crosscheck_distance_m","coordinate_privacy_note"]
    write_csv(OUT/"facilities_verified_coordinates.csv",derived,fields)

    orig_missing=sum(not (r.get("latitude") or "").strip() or not (r.get("longitude") or "").strip() for r in birth)
    final_missing=sum(not (r.get("verified_latitude") or "").strip() or not (r.get("verified_longitude") or "").strip() for r in derived)
    hidden_missing=sum((r.get("is_address_visible") or "").lower()=="false" and (not (r.get("latitude") or "").strip() or not (r.get("longitude") or "").strip()) for r in birth)
    summary={
      "generated_at_utc":datetime.now(timezone.utc).isoformat(),
      "snapshot_year":2026,
      "official_source_date":SOURCE_DATE,
      "official_source_urls":SOURCES,
      "policy":"Only exact normalized name + prefecture + municipality + full visible address matches are auto-filled. Hidden addresses are never inferred. Prefix matches are audit candidates only.",
      "original_missing_coordinates":orig_missing,
      "exact_official_coordinate_fills":exact_fills,
      "remaining_missing_coordinates":final_missing,
      "hidden_address_missing_coordinates_not_inferred":hidden_missing,
      "visible_address_prefix_candidates_not_autofilled":prefix_candidates,
      "ambiguous_visible_name_municipality_matches":ambiguous,
      "existing_birth_navi_coordinates_crosschecked_by_exact_official_match":verified_existing,
      "crosscheck_distance_over_100m":discrepancies_100,
      "crosscheck_distance_over_500m":discrepancies_500,
      "crosscheck_distance_over_1000m":discrepancies_1000,
      "candidate_rows":len(candidates)
    }
    (OUT/"coordinate_verification_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
