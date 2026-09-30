#!/usr/bin/env python3
"""Discover Birth Navi facility IDs from robots.txt + sitemap with minimal load."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

BASE = "https://birth-navi.mhlw.go.jp"
DEFAULT_SITEMAP = BASE + "/sitemap.xml"
FACILITY_RE = re.compile(r"^https://birth-navi\.mhlw\.go\.jp/facilities/(\d+)$")
VERSION = "1.0.0"

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def user_agent(contact: str) -> str:
    return f"G-CHAM-Perinatal-Database/{VERSION} (+https://github.com/GISPHN/G-CHAM-Perinatal-Database; contact={contact})"

def fetch(url: str, contact: str, timeout: float) -> tuple[bytes, dict]:
    req = Request(url, headers={
        "User-Agent": user_agent(contact),
        "Accept": "application/xml,text/xml,text/plain,*/*;q=0.5",
        "Accept-Encoding": "gzip",
    }, method="GET")
    with urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        headers = {k.lower(): v for k, v in resp.headers.items()}
        if headers.get("content-encoding", "").lower() == "gzip" or url.lower().endswith(".gz"):
            try:
                data = gzip.decompress(data)
            except OSError:
                pass
        return data, {"status": getattr(resp, "status", 200), "final_url": resp.geturl()}

def parse_sitemap_declarations(text: str) -> list[str]:
    out = []
    seen = set()
    for line in text.splitlines():
        m = re.match(r"^\s*Sitemap\s*:\s*(\S+)\s*$", line, re.I)
        if m and m.group(1) not in seen:
            out.append(m.group(1)); seen.add(m.group(1))
    return out

def localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]

def parse_xml(data: bytes) -> tuple[str, list[dict[str, str]]]:
    root = ET.fromstring(data)
    kind = localname(root.tag)
    records = []
    expected = "url" if kind == "urlset" else "sitemap" if kind == "sitemapindex" else None
    if expected is None:
        return kind, records
    for child in list(root):
        if localname(child.tag) != expected:
            continue
        rec = {}
        for elem in list(child):
            name = localname(elem.tag)
            if name in {"loc", "lastmod"} and elem.text:
                rec[name] = elem.text.strip()
        if rec.get("loc"):
            records.append(rec)
    return kind, records

def same_host(url: str) -> bool:
    p = urlparse(url)
    return p.scheme in {"http", "https"} and p.hostname == "birth-navi.mhlw.go.jp"

def write_outputs(outdir: Path, rows: list[dict[str, str]], metadata: dict) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "facility_ids.txt").write_text("\n".join(r["birth_navi_id"] for r in rows) + "\n", encoding="utf-8")
    with (outdir / "facility_urls.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["birth_navi_id", "facility_url", "sitemap_lastmod"])
        w.writeheader(); w.writerows(rows)
    (outdir / "discovery_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", required=True)
    ap.add_argument("--outdir", default="work/discovery")
    ap.add_argument("--contact", required=True)
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--delay", type=float, default=2.0)
    ap.add_argument("--max-sitemaps", type=int, default=10)
    a = ap.parse_args()

    outdir = Path(a.outdir)
    rawdir = outdir / "discovery_raw"
    rawdir.mkdir(parents=True, exist_ok=True)
    request_log = []
    errors = []

    robots_url = BASE + "/robots.txt"
    try:
        robots, info = fetch(robots_url, a.contact, a.timeout)
    except (HTTPError, URLError, TimeoutError) as e:
        print(f"Failed robots.txt: {e}", file=sys.stderr); return 2
    (rawdir / "robots.txt").write_bytes(robots)
    request_log.append({"url": robots_url, "status": info["status"], "sha256": sha256_bytes(robots)})

    declared = [u for u in parse_sitemap_declarations(robots.decode("utf-8", "replace")) if same_host(u)]
    queue = declared[:] if declared else [DEFAULT_SITEMAP]
    seen = set()
    facilities: dict[str, dict[str, str]] = {}

    while queue:
        if len(seen) >= a.max_sitemaps:
            errors.append("sitemap request cap reached"); break
        url = queue.pop(0)
        if url in seen:
            continue
        if not same_host(url):
            errors.append(f"off-host sitemap skipped: {url}"); continue
        if seen:
            time.sleep(max(0.0, a.delay))
        try:
            data, info = fetch(url, a.contact, a.timeout)
        except (HTTPError, URLError, TimeoutError) as e:
            errors.append(f"failed sitemap {url}: {e}"); break
        seen.add(url)
        fname = f"sitemap_{len(seen):02d}.xml"
        (rawdir / fname).write_bytes(data)
        request_log.append({"url": url, "status": info["status"], "sha256": sha256_bytes(data), "file": fname})
        try:
            kind, entries = parse_xml(data)
        except ET.ParseError as e:
            errors.append(f"XML parse error: {e}"); break

        if kind == "sitemapindex":
            for rec in entries:
                if same_host(rec["loc"]) and rec["loc"] not in seen and rec["loc"] not in queue:
                    queue.append(rec["loc"])
        elif kind == "urlset":
            for rec in entries:
                m = FACILITY_RE.fullmatch(rec["loc"].strip())
                if m:
                    fid = m.group(1)
                    current = facilities.get(fid)
                    candidate = {"birth_navi_id": fid, "facility_url": rec["loc"].strip(), "sitemap_lastmod": rec.get("lastmod", "")}
                    if current is None or (not current.get("sitemap_lastmod") and candidate["sitemap_lastmod"]):
                        facilities[fid] = candidate
        else:
            errors.append(f"unexpected sitemap root: {kind}"); break

    rows = sorted(facilities.values(), key=lambda r: int(r["birth_navi_id"]))
    ids = [r["birth_navi_id"] for r in rows]
    duplicate = len(ids) != len(set(ids))
    complete = bool(rows) and not duplicate and not errors and not queue
    metadata = {
        "source": "MHLW Birth Navi sitemap",
        "base_url": BASE,
        "retrieved_at_utc": now_iso(),
        "facility_count": len(rows),
        "facility_lastmod_count": sum(bool(r["sitemap_lastmod"]) for r in rows),
        "http_request_count": 1 + len(seen),
        "robots_sitemap_declarations": declared,
        "sitemaps_fetched": sorted(seen),
        "duplicate_ids": duplicate,
        "complete_under_protocol": complete,
        "errors_or_warnings": errors,
        "notes": "Only canonical /facilities/{id} URLs were accepted; no facility detail page was fetched.",
        "requests": request_log,
    }
    write_outputs(outdir, rows, metadata)
    print(f"Facility IDs: {len(rows)}")
    print(f"HTTP requests: {metadata['http_request_count']}")
    print(f"Completeness: {'OK' if complete else 'CHECK'}")
    if errors:
        for e in errors: print("WARNING:", e)
    return 0 if complete else 4

if __name__ == "__main__":
    raise SystemExit(main())
