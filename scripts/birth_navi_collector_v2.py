#!/usr/bin/env python3
"""Resilient annual collector for G-CHAM Perinatal Database.

This wrapper keeps the conservative request behavior of birth_navi_collector.py,
but treats sitemap-listed facility pages returning HTTP 404 or 410 as an
auditable source inconsistency instead of aborting the entire annual snapshot.
"""
from __future__ import annotations

import argparse
import re
import requests
from pathlib import Path

import birth_navi_collector as base


def status_row(fid, url, retrieved_at, http_status, retrieval_status, source_hash="", source_last_modified_at=""):
    return {
        "birth_navi_id": fid,
        "source_url": url,
        "retrieved_at_utc": retrieved_at,
        "http_status": http_status,
        "retrieval_status": retrieval_status,
        "source_last_modified_at": source_last_modified_at,
        "raw_response_sha256": source_hash,
        "parser_version": base.PARSER_VERSION,
    }


class ResilientFetcher(base.Fetcher):
    def fetch(self, fid: int):
        url = f"{base.BASE_URL}/facilities/{fid}"
        if self.robots is None:
            self.load_robots()
        if not self.robots.can_fetch(self.robot_user_agent, url):
            raise RuntimeError(f"robots.txt does not allow {url}")

        self.sleep()
        try:
            r = self.session.get(url, timeout=self.timeout, allow_redirects=True)
        except requests.RequestException as e:
            raise RuntimeError(f"Request failed for {url}: {e}") from e
        self.last_request = base.time.monotonic()
        retrieved = base.now_iso()

        # Safety-stop responses still abort the run.
        if r.status_code in {403, 429, 503} or 500 <= r.status_code < 600:
            raise RuntimeError(
                f"Safety stop HTTP {r.status_code} for {url}; do not immediately retry"
            )

        # A sitemap can temporarily contain a facility URL whose detail page has
        # already disappeared. Preserve the observation, but do not fabricate data.
        if r.status_code in {404, 410}:
            base.append_csv(
                self.outdir / "tables" / "collection_status.csv",
                [status_row(fid, url, retrieved, r.status_code, f"http_{r.status_code}")],
            )
            return {
                "id": fid,
                "name": "",
                "__retrieval_status__": f"http_{r.status_code}",
            }

        if not r.ok:
            raise RuntimeError(f"HTTP {r.status_code} for {url}")

        html = r.text
        facility = base.extract_facility(html)
        if str(facility.get("id")) != str(fid):
            raise RuntimeError(
                f"Facility ID mismatch requested={fid} parsed={facility.get('id')}"
            )

        response_hash = base.sha256_text(html)
        base.export_tables(
            facility,
            self.outdir / "tables",
            url,
            retrieved,
            response_hash,
        )
        base.append_csv(
            self.outdir / "tables" / "collection_status.csv",
            [
                status_row(
                    fid,
                    url,
                    retrieved,
                    200,
                    "ok",
                    response_hash,
                    facility.get("lastModifiedAt") or "",
                )
            ],
        )
        return facility


def read_ids(path: Path):
    out = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        m = re.search(r"(\d+)", line.strip())
        if m:
            out.append(int(m.group(1)))
    return list(dict.fromkeys(out))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids-file", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--contact", required=True)
    ap.add_argument("--delay", type=float, default=base.DEFAULT_DELAY)
    ap.add_argument("--jitter", type=float, default=base.DEFAULT_JITTER)
    ap.add_argument("--timeout", type=float, default=base.DEFAULT_TIMEOUT)
    ap.add_argument("--confirm-batch", action="store_true")
    a = ap.parse_args()

    ids = read_ids(Path(a.ids_file))
    if len(ids) > 20 and not a.confirm_batch:
        raise SystemExit("Safety stop: >20 facilities requires --confirm-batch")

    f = ResilientFetcher(Path(a.outdir), a.contact, a.delay, a.jitter, a.timeout)
    print(
        f"Sequentially processing {len(ids)} facilities; "
        f"delay >= {a.delay}s + jitter <= {a.jitter}s"
    )
    for i, fid in enumerate(ids, 1):
        facility = f.fetch(fid)
        status = facility.get("__retrieval_status__")
        if status:
            print(f"[{i}/{len(ids)}] {fid} UNAVAILABLE {status}")
        else:
            print(f"[{i}/{len(ids)}] {fid} OK {facility.get('name')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
