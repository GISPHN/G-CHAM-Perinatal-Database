#!/usr/bin/env python3
from __future__ import annotations
import csv, io, json, re, unicodedata, urllib.request, zipfile
from difflib import SequenceMatcher
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/"data/quality/2026/unresolved_visible_address_coordinates.csv"
OUT=ROOT/"data/quality/2026/priority22_official_coordinate_candidates.csv"
SOURCES={
 "hospital":"https://www.mhlw.go.jp/content/11121000/01-1_hospital_facility_info_20260601.csv.zip",
 "clinic":"https://www.mhlw.go.jp/content/11121000/02-1_clinic_facility_info_20260601.csv.zip",
 "maternity_home":"https://www.mhlw.go.jp/content/11121000/04_maternity_home_20260601.csv.zip",
}

def norm(s):
    s=unicodedata.normalize("NFKC",s or "").lower()
    for x in ["医療法人社団","医療法人","社会福祉法人","財団法人","一般財団法人","公益財団法人","地方独立行政法人","独立行政法人","国家公務員共済組合連合会"]:
        s=s.replace(x,"")
    return "".join(ch for ch in s if ch.isalnum())

def read(path):
    with path.open("r",encoding="utf-8-sig",newline="") as f:return list(csv.DictReader(f))

def load():
    rows=[]
    for kind,url in SOURCES.items():
        req=urllib.request.Request(url,headers={"User-Agent":"G-CHAM-Perinatal-Database/1.0"})
        with urllib.request.urlopen(req,timeout=90) as r: raw=r.read()
        z=zipfile.ZipFile(io.BytesIO(raw))
        name=next(n for n in z.namelist() if n.lower().endswith(".csv"))
        for x in csv.DictReader(io.StringIO(z.read(name).decode("utf-8-sig"))):
            x["_source"]=kind; x["_n"]=norm(x.get("正式名称","")); rows.append(x)
    return rows

def main():
    src=read(SRC)
    targets=[r for r in src if r.get("facility_type")]
    off=load()
    out=[]
    for t in targets:
        tn=norm(t["facility_name"])
        pref=str(t.get("prefecture_id") or "").zfill(2)
        code=str(t.get("facility_type_code") or "")
        expected={"1":"hospital","2":"clinic","3":"clinic","4":"maternity_home","5":"maternity_home"}.get(code)
        cands=[]
        for o in off:
            if expected and o["_source"]!=expected: continue
            op=str(o.get("都道府県コード") or "").zfill(2)
            if pref and op!=pref: continue
            sim=SequenceMatcher(None,tn,o["_n"]).ratio()
            if tn and (tn in o["_n"] or o["_n"] in tn): sim=max(sim,.95)
            if sim>=.55:
                cands.append((sim,o))
        cands.sort(key=lambda z:z[0],reverse=True)
        for rank,(sim,o) in enumerate(cands[:5],1):
            out.append({
              "birth_navi_id":t["birth_navi_id"],"facility_name":t["facility_name"],"facility_type":t["facility_type"],
              "birth_navi_address":t["address"],"birth_navi_phone":t["phone_number"],"rank":rank,"name_similarity":f"{sim:.4f}",
              "official_source":o["_source"],"official_id":o.get("ID",""),"official_name":o.get("正式名称",""),
              "official_address":o.get("所在地",""),"official_latitude":o.get("所在地座標（緯度）",""),"official_longitude":o.get("所在地座標（経度）","")
            })
    fields=list(out[0].keys())
    with OUT.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(out)
    print(json.dumps({"targets":len(targets),"candidate_rows":len(out)},ensure_ascii=False))

if __name__=="__main__":main()
