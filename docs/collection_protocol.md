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

## Nationwide taxable-household postnatal-care study

This study-specific observation is separate from the annual facility-page
collector. It extends the validated Nara and Western Japan datasets to all 47
prefectures. On 2026-10-28, the public Birth Navi facility-page loader was
queried for each of the 4,600 municipality-listing relations in
`data/derived/2026/municipality_postnatal_services.csv`. Each
request selected the relation's resident municipality and household type
`住民税課税世帯` (`household_type = 1`). The current public municipality list
was obtained for every prefecture so that municipalities absent from the
2026 relation snapshot remain visible in the summary table.

Collection used at most eight workers, a global minimum interval of 0.2 seconds
between request starts, bounded retries with backoff, and an atomic per-relation
cache. The cache makes interrupted runs restartable without repeating completed
requests. No unrecoverable request or decoding errors remained in the completed
run. The displayed facility name, eligibility, general remarks, method-specific
fee text, included items, maximum use, eligible infant age, multiple-birth
acceptance, sibling acceptance, service notes, source update time, source URL,
and retrieval time were retained. Application-procedure fields were not
included.

The nationwide source UI observations are stored in:

- `data/snapshots/2026/nationwide_postnatal_taxable_relations.csv`;
- `data/snapshots/2026/nationwide_postnatal_taxable_services.csv`.

The source display was not forced into the earlier annual service-type schema.
When the UI displayed no method-level detail after all three selections, the
relation was retained with
`detail_status = no_service_details_displayed_after_selection`. It was not
encoded as zero cost or service absence. Differences between the annual
snapshot service codes and the UI observation are published separately under
`data/quality/2026/`.

Fee normalization is conservative. A single displayed amount can populate
`fee_yen`; a range populates only `fee_min_yen` and `fee_max_yen`; several
duration-specific prices remain `multiple_tiers`; and missing or
contact-required prices retain blank numeric values. The raw display text is
authoritative for reanalysis.

The completed study contains 4,600 relation observations and 6,493 displayed
service options. Of the relations, 429 displayed no method-level details after
selection. Four annual-snapshot relations returned HTTP 404 at collection time
and are retained with `detail_status = source_page_not_found`. The municipality
summary retains all 1,912 current municipalities: 1,201 have at least one
relation in the 2026 source snapshot and 711 do not. Absence from that source
relation snapshot is not evidence that a
municipality has no postnatal-care program or a zero user fee.

The original Nara and Western Japan study files remain available as validated
subsets. The 1,953 Western Japan relations and 2,852 service rows match their
nationwide counterparts on the substantive displayed fields.
