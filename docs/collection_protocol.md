# Collection protocol

## Objective

Create one reproducible annual snapshot of facility-specific information publicly displayed by MHLW Birth Navi while minimizing load on the source website.

## Frequency

- Scheduled: once annually, April 1.
- Manual: `workflow_dispatch`, intended for the exceptional 2026 initial snapshot and controlled reruns after review.

## Request model

- Facility discovery: `robots.txt` plus sitemap(s).
- Facility detail: one GET to the canonical `/facilities/{id}` HTML page per facility.
- No browser automation.
- No JavaScript/CSS/image/font/map requests.
- No municipality-dependent prenatal/postnatal APIs in the initial implementation.
- Eight deterministic sequential shards; GitHub Actions `max-parallel: 1`.
- Default delay: 10 seconds + random jitter up to 2 seconds between facility requests.

## Safety stops

Collection stops on unverifiable/disallowing `robots.txt`, HTTP 429, HTTP 503, repeated HTTP errors, missing React Router loader data, facility-object parsing failure, or validation failure.

## Provenance retained

For each facility, normalized output retains the Birth Navi ID, source URL, retrieval UTC timestamp, source `lastModifiedAt` when available, response SHA-256, and parser version. Raw HTML is ephemeral and is not committed to the repository.

## Longitudinal interpretation

Snapshots are annual observations. A value difference between years indicates that a change was observed between the two snapshot dates; it does not identify the exact change date.
