#!/usr/bin/env python3
"""Low-load Birth Navi collector for G-CHAM Perinatal Database.

Facility-specific information only. Municipality-dependent APIs are intentionally
excluded. The collector performs one canonical HTML GET per facility, parses the
server-rendered React Router payload, and emits normalized CSV tables.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import robotparser

import requests

BASE_URL = "https://birth-navi.mhlw.go.jp"
PARSER_VERSION = "1.0.0"
DEFAULT_DELAY = 10.0
DEFAULT_JITTER = 2.0
DEFAULT_TIMEOUT = 30.0

FACILITY_TYPE = {1:"病院",2:"有床診療所",3:"無床診療所",4:"有床助産所",5:"無床助産所"}
DELIVERY_TYPE = {1:"自施設での分娩取扱あり",2:"オープンシステムを利用し、他施設へ赴いての分娩取扱あり",3:"自宅分娩（出張分娩）での分娩取扱あり",4:"なし",100:"あり"}
POSTNATAL_CARE_TYPE = {1:"短期入所（ショートステイ）型",2:"通所（デイサービス）型（個別）",3:"通所（デイサービス）型（集団）",4:"居宅訪問（アウトリーチ）型"}
PRENATAL_TYPE = {1:"自施設で分娩予定の方の妊娠健康診査対応可能",2:"他施設で分娩予定の方の妊娠健康診査対応可能"}
DAY_OF_WEEK = {0:"祝日",1:"月",2:"火",3:"水",4:"木",5:"金",6:"土",7:"日"}
SPECIALS = {-1:"__hole__",-2:None,-3:math.inf,-4:-math.inf,-5:None,-6:-0.0}

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def money_int(value: Any):
    if value is None: return None
    if isinstance(value,(int,float)) and not isinstance(value,bool): return int(value)
    m=re.search(r"([0-9][0-9,]*)",str(value))
    return int(m.group(1).replace(",","")) if m else None

def codes(values) -> str:
    return ";".join(str(x) for x in (values or []))

def labels(values,mapping) -> str:
    return ";".join(mapping.get(x,f"code:{x}") for x in (values or []))

def parse_payload(html: str) -> dict[str,Any]:
    pattern=re.compile(r'streamController\.enqueue\(("(?:\\.|[^"\\])*")\)',re.S)
    candidates=[]
    for m in pattern.finditer(html):
        try: s=json.loads(m.group(1))
        except json.JSONDecodeError: continue
        if "loaderData" in s: candidates.append(s)
    if not candidates:
        raise ValueError("React Router loaderData payload not found")
    last=None
    for s in candidates:
        try: return decode_devalue(json.loads(s))
        except Exception as e: last=e
    raise ValueError(f"Unable to decode React Router payload: {last}")

def decode_devalue(table):
    if not isinstance(table,list) or not table:
        raise ValueError("Unexpected devalue payload")
    memo={}
    def dec(ref):
        if isinstance(ref,int) and ref < 0: return SPECIALS.get(ref)
        if not isinstance(ref,int): return ref
        if ref in memo: return memo[ref]
        node=table[ref]
        if isinstance(node,dict):
            out={}; memo[ref]=out
            for kr,vr in node.items():
                if isinstance(kr,str) and kr.startswith("_"):
                    out[dec(int(kr[1:]))]=dec(vr)
            return out
        if isinstance(node,list):
            if node and isinstance(node[0],str):
                out={"__type__":node[0],"value":dec(node[1]) if len(node)>1 and isinstance(node[1],int) else node[1:]}
                memo[ref]=out; return out
            out=[]; memo[ref]=out; out.extend(dec(v) for v in node); return out
        memo[ref]=node; return node
    return dec(0)

def extract_facility(html: str) -> dict[str,Any]:
    root=parse_payload(html)
    loader=root.get("loaderData",{})
    key=next((k for k in loader if "FacilityDetail" in str(k) and "Map" not in str(k)),None)
    if key is None:
        key=next((k for k in loader if "FacilityDetail" in str(k)),None)
    if key is None: raise ValueError("FacilityDetail loader not found")
    detail=loader[key]
    facility=detail.get("facility") if isinstance(detail,dict) else None
    if not isinstance(facility,dict): raise ValueError("Facility object not found")
    return facility

def service_flags(f):
    p=f.get("prenatalCheckup")
    prenatal=isinstance(p,dict) and p.get("canPrenatalCheckup") is not False
    d=f.get("delivery") or {}; types=d.get("types") or []
    delivery=bool(types) and 4 not in types
    postnatal=isinstance(f.get("facilityPostnatalCare"),dict)
    names=[]
    if prenatal: names.append("prenatal")
    if delivery: names.append("delivery")
    if postnatal: names.append("postnatal")
    return {"prenatal_checkup_listed":int(prenatal),"delivery_listed":int(delivery),"postnatal_care_listed":int(postnatal),"service_count":len(names),"service_pattern":"+".join(names) if names else "none"}

def normalize(f, source_url, retrieved_at, response_hash):
    fid=f.get("id"); municipality=f.get("municipality") or {}
    address_visible=f.get("isAddressVisible") is not False
    phone_visible=f.get("isPhoneNumberVisible") is not False
    flags=service_flags(f)
    facilities=[{
        "birth_navi_id":fid,"facility_name":f.get("name"),"facility_name_kana":f.get("nameKatakana"),
        "facility_type_code":f.get("type"),"facility_type":FACILITY_TYPE.get(f.get("type"),""),
        "prefecture_id":municipality.get("prefectureId"),"municipality_code":municipality.get("code"),"municipality_name":municipality.get("name"),
        "address":f.get("address") if address_visible else "","is_address_visible":f.get("isAddressVisible"),
        "phone_number":f.get("phoneNumber") if phone_visible else "","is_phone_number_visible":f.get("isPhoneNumberVisible"),
        "latitude":f.get("latitude"),"longitude":f.get("longitude"),"has_parking":f.get("hasParking"),"access_method":f.get("accessMethod"),
        "is_listed":f.get("isListed"),"source_last_modified_at":f.get("lastModifiedAt"),**flags,
        "source_url":source_url,"retrieved_at_utc":retrieved_at,"parser_version":PARSER_VERSION,"raw_response_sha256":response_hash
    }]
    eq=f.get("equipment") or {}; hosp=f.get("hospitalization") or {}; hd=f.get("hospitalizationDay") or {}
    tests=f.get("testsAndScreening") or {}; mid=f.get("midwiferyCareService") or {}; staff=f.get("professionalStaff") or {}
    detail=[{
        "birth_navi_id":fid,"perinatal_medical_center_type":eq.get("perinatalMedicalCenterType"),"obstetrics_unit_type":eq.get("obstetricsUnitType"),
        "nicu_bed_count":eq.get("nicuBedCount"),"maternity_bed_count":eq.get("maternityBedCount"),"has_birth_center_bed_count":eq.get("hasBirthCenterBedCount"),
        "has_private_room":hosp.get("hasPrivateRoom"),"need_pay_difference":hosp.get("needPayDifference"),"visitor_relationship_codes":codes(hosp.get("visitorRelationships")),
        "hospitalization_days_average":hd.get("hospitalizationDaysAverage"),"hospitalization_days_median":hd.get("hospitalizationDaysMedian"),
        "hospitalization_days_q1":hd.get("hospitalizationDaysQ1"),"hospitalization_days_q3":hd.get("hospitalizationDaysQ3"),
        "can_hearing_test":tests.get("canHearingTest"),"can_provide_hearing_test_facility_info":tests.get("canProvideHearingTestFacilityInfo"),
        "can_two_week_checkup":tests.get("canTwoWeekCheckup"),"can_one_month_checkup":tests.get("canOneMonthCheckup"),
        "neonatal_checkup_codes":codes(tests.get("neonatalCheckups")),"can_rubella_vaccination":tests.get("canRubellaVaccination"),
        "midwifery_can_outpatient":mid.get("canOutpatient"),"midwifery_can_in_hospital":mid.get("canInHospital"),
        "can_in_hospital_breastfeeding_support":mid.get("canInHospitalBreastfeedingSupport"),"breastfeeding_support_after_discharge":mid.get("breastfeedingSupportAfterDischarge"),
        "obstetrician_count":staff.get("obstetricianCount"),"pediatrician_count":staff.get("pediatricianCount"),"midwife_count":staff.get("midwifeCount"),
        "advanced_midwife_count":staff.get("advancedMidwifeCount"),"nurse_count":staff.get("nurseCount")
    }]
    d=f.get("delivery") or {}; p=f.get("painlessDelivery") or {}; a=f.get("attendedDelivery") or {}; c=f.get("deliveryCost") or {}
    delivery=[{
        "birth_navi_id":fid,"delivery_type_codes":codes(d.get("types")),"delivery_type_labels":labels(d.get("types"),DELIVERY_TYPE),
        "reservation_method_codes":codes(d.get("reservationMethods")),"mother_child_rooming_in":d.get("canMotherChildRoomingIn"),
        "can_hometown_delivery":d.get("canHometownDelivery"),"hometown_delivery_checkup_weeks":d.get("hometownDeliveryCheckupWeeks"),
        "vaginal_delivery_count_text":d.get("vaginalDeliveryCountText"),"cesarean_delivery_count_text":d.get("cesareanDeliveryCountText"),
        "can_provide_umbilical_blood_bank":d.get("canProvideUmbilicalBloodBank"),"painless_delivery_policy":p.get("painlessDeliveryPolicy"),
        "anesthesia_method_codes":codes(p.get("anesthesiaMethods")),"anesthesia_qualification_codes":codes(p.get("anesthesiaQualificationTypes")),
        "painless_availability_hour":p.get("availabilityHour"),"labor_induction_available":p.get("laborInductionAvailable"),
        "painless_delivery_count_text":p.get("painlessDeliveryCountText"),"has_listed_on_jala":p.get("hasListedOnJala"),"jala_url":p.get("jalaUrl"),
        "can_attended_delivery":a.get("canAttendedDelivery"),"attendee_relationship_codes":codes(a.get("attendeeRelationships")),
        "total_cost_average":c.get("totalCostAverage"),"total_cost_median":c.get("totalCostMedian"),"total_cost_q1":c.get("totalCostQ1"),"total_cost_q3":c.get("totalCostQ3"),
        "delivery_cost_average":c.get("deliveryCostAverage"),"delivery_cost_median":c.get("deliveryCostMedian"),"delivery_cost_q1":c.get("deliveryCostQ1"),"delivery_cost_q3":c.get("deliveryCostQ3"),
        "room_difference_average":c.get("roomDifferenceAverage"),"room_difference_median":c.get("roomDifferenceMedian"),"room_difference_q1":c.get("roomDifferenceQ1"),"room_difference_q3":c.get("roomDifferenceQ3")
    }]
    pc=f.get("prenatalCheckup") or {}
    prenatal=[{"birth_navi_id":fid,"can_prenatal_checkup":pc.get("canPrenatalCheckup"),"can_pregnancy_checkup":pc.get("canPregnancyCheckup"),
              "prenatal_type_codes":codes(pc.get("types")),"prenatal_type_labels":labels(pc.get("types"),PRENATAL_TYPE),
              "prenatal_total_cost_text":pc.get("totalCost"),"prenatal_total_cost_yen":money_int(pc.get("totalCost"))}]
    prenatal_details=[{"birth_navi_id":fid,"period":x.get("period"),"standard_checkup_codes":codes(x.get("standardCheckups")),
                      "additional_checkup_codes":codes(x.get("additionalCheckups")),"additional_checkup_other":x.get("additionalCheckupOther"),
                      "cost_text":x.get("cost"),"cost_yen":money_int(x.get("cost"))} for x in (pc.get("details") or []) if isinstance(x,dict)]
    prenatal_options=[{"birth_navi_id":fid,"checkup_item":x.get("checkupItem"),"cost_text":x.get("cost"),"cost_yen":money_int(x.get("cost"))} for x in (pc.get("options") or []) if isinstance(x,dict)]
    pregnancy_checks=[{"birth_navi_id":fid,"pregnancy_checkup_type":x.get("type"),"total_cost_text":x.get("totalCost"),"total_cost_yen":money_int(x.get("totalCost")),
                       "item_type_codes":codes((y or {}).get("type") for y in (x.get("items") or []))} for x in (pc.get("pregnancyCheckup") or []) if isinstance(x,dict)]
    post=f.get("facilityPostnatalCare") or {}
    postnatal=[]
    for x in (post.get("types") or []):
        code=x.get("postnatalCareType") if isinstance(x,dict) else x
        postnatal.append({"birth_navi_id":fid,"postnatal_care_type_code":code,"postnatal_care_type":POSTNATAL_CARE_TYPE.get(code,f"code:{code}")})
    outpatient=[{"birth_navi_id":fid,"day_of_week_code":x.get("dayOfWeek"),"day_of_week":DAY_OF_WEEK.get(x.get("dayOfWeek"),f"code:{x.get('dayOfWeek')}"),
                 "reception_time_text":x.get("receptionTimeText"),"has_outpatient":x.get("hasOutpatient")} for x in (f.get("outpatientReceptionTimes") or []) if isinstance(x,dict)]
    external=[{"birth_navi_id":fid,"external_site_type_code":x.get("type"),"url":x.get("url")} for x in (f.get("externalSites") or []) if isinstance(x,dict)]
    room=[{"birth_navi_id":fid,"room_type_code":x.get("type"),"need_pay_difference":x.get("needPayDifference"),"cost_text":x.get("costText"),
           "cost_yen":money_int(x.get("costText")),"room_form_other":x.get("roomFormOther")} for x in (f.get("roomCosts") or []) if isinstance(x,dict)]
    painless=[{"birth_navi_id":fid,"item":x.get("item"),"cost_text":x.get("cost"),"cost_yen":money_int(x.get("cost"))} for x in (f.get("painlessDeliveryCosts") or []) if isinstance(x,dict)]
    return {"facilities":facilities,"facility_detail":detail,"delivery":delivery,"prenatal":prenatal,"prenatal_checkup_details":prenatal_details,
            "prenatal_options":prenatal_options,"pregnancy_checkups":pregnancy_checks,"postnatal_services":postnatal,"outpatient_times":outpatient,
            "external_sites":external,"room_costs":room,"painless_delivery_costs":painless}

def append_csv(path: Path, rows):
    if not rows: return
    path.parent.mkdir(parents=True,exist_ok=True)
    mode="a" if path.exists() else "w"
    fields=list(rows[0].keys())
    with path.open(mode,encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore")
        if mode=="w": w.writeheader()
        w.writerows(rows)

def export_tables(f, outdir, url, retrieved, response_hash):
    for name,rows in normalize(f,url,retrieved,response_hash).items():
        append_csv(outdir/f"{name}.csv",rows)

@dataclass
class Fetcher:
    outdir: Path
    contact: str
    delay: float=DEFAULT_DELAY
    jitter: float=DEFAULT_JITTER
    timeout: float=DEFAULT_TIMEOUT

    def __post_init__(self):
        self.session=requests.Session()
        self.robot_user_agent="G-CHAM-Perinatal-Database"
        self.session.headers.update({
            "User-Agent":f"G-CHAM-Perinatal-Database/{PARSER_VERSION} (+https://github.com/GISPHN/G-CHAM-Perinatal-Database; contact={self.contact})",
            "Accept":"text/html,application/xhtml+xml","Accept-Language":"ja,en;q=0.5","Accept-Encoding":"gzip, deflate"
        })
        self.last_request=0.0
        self.robots=None

    def sleep(self):
        target=max(0.0,self.delay)+random.uniform(0,max(0.0,self.jitter))
        elapsed=time.monotonic()-self.last_request
        if elapsed < target: time.sleep(target-elapsed)

    def load_robots(self):
        url=BASE_URL+"/robots.txt"
        r=self.session.get(url,timeout=self.timeout)
        self.last_request=time.monotonic()
        if not r.ok: raise RuntimeError(f"robots.txt returned HTTP {r.status_code}")
        rp=robotparser.RobotFileParser(); rp.parse(r.text.splitlines()); self.robots=rp

    def fetch(self, fid: int):
        url=f"{BASE_URL}/facilities/{fid}"
        if self.robots is None: self.load_robots()
        if not self.robots.can_fetch(self.robot_user_agent,url):
            raise RuntimeError(f"robots.txt does not allow {url}")
        self.sleep()
        try:
            r=self.session.get(url,timeout=self.timeout,allow_redirects=True)
        except requests.RequestException as e:
            raise RuntimeError(f"Request failed for {url}: {e}") from e
        self.last_request=time.monotonic()
        if r.status_code in {403,429,503} or 500 <= r.status_code < 600:
            raise RuntimeError(f"Safety stop HTTP {r.status_code} for {url}; do not immediately retry")
        if not r.ok:
            raise RuntimeError(f"HTTP {r.status_code} for {url}")
        html=r.text
        facility=extract_facility(html)
        if str(facility.get("id")) != str(fid):
            raise RuntimeError(f"Facility ID mismatch requested={fid} parsed={facility.get('id')}")
        retrieved=now_iso()
        export_tables(facility,self.outdir/"tables",url,retrieved,sha256_text(html))
        return facility

def read_ids(path: Path):
    out=[]
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        m=re.search(r"(\d+)",line.strip())
        if m: out.append(int(m.group(1)))
    return list(dict.fromkeys(out))

def main() -> int:
    ap=argparse.ArgumentParser()
    sub=ap.add_subparsers(dest="cmd",required=True)
    p=sub.add_parser("fetch")
    p.add_argument("--ids-file",required=True); p.add_argument("--outdir",required=True); p.add_argument("--contact",required=True)
    p.add_argument("--delay",type=float,default=DEFAULT_DELAY); p.add_argument("--jitter",type=float,default=DEFAULT_JITTER)
    p.add_argument("--timeout",type=float,default=DEFAULT_TIMEOUT); p.add_argument("--confirm-batch",action="store_true")
    a=ap.parse_args()
    ids=read_ids(Path(a.ids_file))
    if len(ids)>20 and not a.confirm_batch:
        raise SystemExit("Safety stop: >20 facilities requires --confirm-batch")
    f=Fetcher(Path(a.outdir),a.contact,a.delay,a.jitter,a.timeout)
    print(f"Sequentially processing {len(ids)} facilities; delay >= {a.delay}s + jitter <= {a.jitter}s")
    for i,fid in enumerate(ids,1):
        facility=f.fetch(fid)
        print(f"[{i}/{len(ids)}] {fid} OK {facility.get('name')}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
