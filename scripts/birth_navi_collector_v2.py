#!/usr/bin/env python3
"""Resilient annual collector for G-CHAM Perinatal Database.

Facility-specific information only. Municipality-dependent APIs are intentionally
excluded.

Behavior:
- 404/410 from a sitemap-listed facility page are recorded as source
  inconsistencies and do not abort the snapshot.
- transient gateway/server failures (500/502/504) and request-level network
  errors are retried conservatively with long exponential backoff.
- 403/429/503 remain immediate safety stops.
- repeated transient failures still abort the shard so an incomplete annual
  snapshot cannot be published silently.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import requests

import birth_navi_collector as base

TRANSIENT_HTTP = {500, 502, 504}
IMMEDIATE_SAFETY_STOP_HTTP = {403, 429, 503}
MAX_TRANSIENT_RETRIES = 2
BACKOFF_BASE_SECONDS = 30.0
BACKOFF_JITTER_SECONDS = 5.0


def status_row(
    fid,
    url,
    retrieved_at,
    http_status,
    retrieval_status,
    source_hash="",
    source_last_modified_at="",
):
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
    def _backoff(self, retry_number: int, reason: str) -> None:
        wait = (
            BACKOFF_BASE_SECONDS * (2 ** (retry_number - 1))
            + base.random.uniform(0.0, BACKOFF_JITTER_SECONDS)
        )
        print(
            f"Transient failure ({reason}); waiting {wait:.1f}s "
            f"before retry {retry_number}/{MAX_TRANSIENT_RETRIES}."
        )
        base.time.sleep(wait)

    def _get_with_conservative_retry(self, url: str):
        # Initial request follows the normal inter-facility pacing.
        self.sleep()

        attempt = 0
        while True:
            attempt += 1
            try:
                r = self.session.get(
                    url,
                    timeout=self.timeout,
                    allow_redirects=True,
                )
            except requests.RequestException as e:
                self.last_request = base.time.monotonic()
                retries_used = attempt - 1
                if retries_used >= MAX_TRANSIENT_RETRIES:
                    raise RuntimeError(
                        f"Request failed for {url} after {attempt} attempts: {e}"
                    ) from e
                self._backoff(retries_used + 1, e.__class__.__name__)
                continue

            self.last_request = base.time.monotonic()

            if r.status_code in IMMEDIATE_SAFETY_STOP_HTTP:
                raise RuntimeError(
                    f"Safety stop HTTP {r.status_code} for {url}; "
                    "no automatic retry"
                )

            if r.status_code in TRANSIENT_HTTP:
                retries_used = attempt - 1
                if retries_used >= MAX_TRANSIENT_RETRIES:
                    raise RuntimeError(
                        f"Transient HTTP {r.status_code} persisted for {url} "
                        f"after {attempt} attempts"
                    )
                self._backoff(retries_used + 1, f"HTTP {r.status_code}")
                continue

            # Any other 5xx is treated conservatively as a safety stop.
            if 500 <= r.status_code < 600:
                raise RuntimeError(
                    f"Safety stop HTTP {r.status_code} for {url}; "
                    "unclassified server error"
                )

            return r

    def fetch(self, fid: int):
        url = f"{base.BASE_URL}/facilities/{fid}"

        if self.robots is None:
            self.load_robots()
        if not self.robots.can_fetch(self.robot_user_agent, url):
            raise RuntimeError(f"robots.txt does not allow {url}")

        r = self._get_with_conservative_retry(url)
        retrieved = base.now_iso()

        # A sitemap can temporarily contain a facility URL whose detail page has
        # already disappeared. Preserve the observation, but do not fabricate data.
        if r.status_code in {404, 410}:
            base.append_csv(
                self.outdir / "tables" / "collection_status.csv",
                [
                    status_row(
                        fid,
                        url,
                        retrieved,
                        r.status_code,
                        f"http_{r.status_code}",
                    )
                ],
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

    f = ResilientFetcher(
        Path(a.outdir),
        a.contact,
        a.delay,
        a.jitter,
        a.timeout,
    )

    print(
        f"Sequentially processing {len(ids)} facilities; "
        f"delay >= {a.delay}s + jitter <= {a.jitter}s; "
        f"transient retries <= {MAX_TRANSIENT_RETRIES} "
        f"with backoff >= {BACKOFF_BASE_SECONDS:.0f}s."
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
