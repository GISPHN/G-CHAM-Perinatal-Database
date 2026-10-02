#!/usr/bin/env python3
from __future__ import annotations
import csv, io, json, urllib.request, zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"data/quality/2026/official_coordinate_source_probe.json"
SOURCES={
 "hospital":"https://www.mhlw.go.jp/content/11121000/01-1_hospital_facility_info_20260601.csv.zip",
 "clinic":"https://www.mhlw.go.jp/content/11121000/02-1_clinic_facility_info_20260601.csv.zip",
 "maternity_home":"https://www.mhlw.go.jp/content/11121000/04_maternity_home_20260601.csv.zip",
}

def candidates(header, words):
    out=[]
    for h in header:
        s=(h or "").strip().lower()
        if any(w.lower() in s for w in words): out.append(h)
    return out

def main():
    report={"generated_at_utc":datetime.now(timezone.utc).isoformat(),"sources":{}}
    for kind,url in SOURCES.items():
        req=urllib.request.Request(url,headers={"User-Agent":"G-CHAM-Perinatal-Database/1.0 (+https://github.com/GISPHN/G-CHAM-Perinatal-Database)"})
        with urllib.request.urlopen(req,timeout=60) as r:
            raw=r.read()
        z=zipfile.ZipFile(io.BytesIO(raw))
        entries=[]
        for name in z.namelist():
            if not name.lower().endswith(".csv"): continue
            data=z.read(name).decode("utf-8-sig")
            reader=csv.reader(io.StringIO(data))
            header=next(reader)
            first=next(reader,[])
            entries.append({
              "file":name,
              "row_count_estimate":sum(1 for _ in reader)+ (1 if first else 0),
              "header":header,
              "coordinate_candidates":{
                "latitude":candidates(header,["緯度","latitude","lat"]),
                "longitude":candidates(header,["経度","longitude","lon","lng"]),
              },
              "identity_candidates":{
                "name":candidates(header,["施設名","正式名称","医療機関名","助産所名","名称"]),
                "address":candidates(header,["所在地","住所"]),
                "phone":candidates(header,["電話"]),
                "id":candidates(header,["機関コード","施設id","施設id","id"]),
              },
              "first_row_preview":dict(zip(header,first)) if first else {}
            })
        report["sources"][kind]={"url":url,"zip_entries":entries}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
