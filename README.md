# G-CHAM Perinatal Database

**Author: Ryo Horiike**

G-CHAM Perinatal Database is a research-oriented longitudinal database of perinatal-care facilities in Japan. It converts publicly displayed facility information from the Ministry of Health, Labour and Welfare (MHLW) **Birth Navi / 出産なび** website into analysis-ready annual datasets for GIS, public health, health-services research, and reproducible longitudinal analysis.

Repository: https://github.com/GISPHN/G-CHAM-Perinatal-Database

## Scope

The database is designed to preserve annual facility-level information such as:

- facility name, type, municipality, address when publicly displayed, and site-provided latitude/longitude;
- availability of prenatal checkups, delivery, and postnatal-care services;
- perinatal-center functions, NICU/maternity beds, and selected professional staffing counts;
- delivery characteristics, delivery volume categories, painless-delivery information, and hospitalization-related information;
- reported delivery costs and room-related costs;
- prenatal-checkup availability, total cost, and checkup-level items/costs;
- facility-level postnatal-care service types.

**Municipality-dependent information is intentionally excluded from the initial nationwide annual collector.** Therefore, a facility being listed as providing postnatal care does **not** mean that every municipality resident can use that facility. A separate 2026 Western Japan study-specific dataset records publicly displayed postnatal-care information for taxable households; it does not include municipality-specific application procedures.

## Data source and status

Primary source:

- Ministry of Health, Labour and Welfare, Japan. **Birth Navi / 出産なび**: https://birth-navi.mhlw.go.jp/
- Birth Navi terms: https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/iryou/index_00041.html
- MHLW website terms: https://www.mhlw.go.jp/chosakuken/index.html

This repository is **not an official MHLW bulk-data distribution**. It is an independently processed research database created from information publicly displayed on Birth Navi. MHLW states that rights to information published on Birth Navi belong to MHLW and that the source must be indicated when reproducing the information. MHLW's general website terms otherwise apply, including the Public Data License 1.0 framework where applicable.

Birth Navi also notes that facility information is generally published as reported by hospitals, clinics, and midwifery facilities and may not always reflect the latest state. Users should therefore treat the annual snapshot date as an observation date rather than an assurance that every field changed on that date.

## Update frequency

The database is updated **once per year**. The scheduled workflow starts on **April 1** and builds a complete annual snapshot using the then-current Birth Navi sitemap and facility pages.

The workflow is deliberately low-rate:

1. `robots.txt` and the sitemap are checked first.
2. Only canonical `/facilities/{id}` pages listed in the current sitemap are collected.
3. Facility pages are requested sequentially; no parallel requests are made.
4. The default interval is at least 10 seconds plus a random delay of up to 2 seconds.
5. JavaScript, CSS, images, map tiles, fonts, and municipality-dependent APIs are not requested.
6. HTTP 429/503 and structural parsing failures stop the run rather than increasing request pressure.
7. The annual workload is divided into eight sequential GitHub Actions jobs so that each job remains below the hosted-runner time limit without parallelizing requests to Birth Navi.

If a facility URL is present in the current sitemap but its canonical detail page returns HTTP 404 or 410, the workflow now records that discrepancy in `collection_status.csv` and continues. No facility attributes are fabricated for that ID. This distinguishes **sitemap presence** from **detail-page retrievability** and prevents one stale sitemap entry from invalidating the entire annual snapshot.

## 2026 initial snapshot

The regular annual schedule begins with the April workflow. Because this repository was created during 2026, **2026 is treated as an exceptional initial snapshot** and can be generated immediately with the manual GitHub Actions trigger.

Go to:

**Actions → Build annual G-CHAM Perinatal Database snapshot → Run workflow**

For the current initial run, leave `snapshot_year` blank (or enter `2026`). The workflow performs facility discovery, eight sequential collection shards, validation, longitudinal-history generation, and commits the finished snapshot back to the repository. One manual workflow dispatch is sufficient; the user does not need to start each shard separately.

Optional repository secret:

`Settings → Secrets and variables → Actions → New repository secret`

- Name: `BIRTH_NAVI_CONTACT`
- Value: a research contact email address

If the secret is absent, the repository Issues URL is used as the contact identifier in the User-Agent.

## Repository structure

```text
.github/workflows/annual_snapshot.yml  Annual + manual workflow
scripts/                              Collection, parsing, validation, comparison
docs/data_dictionary.csv              Variable/data dictionary
data/snapshots/YYYY/                  Complete annual snapshots
data/history/annual_summary.csv        Annual facility/service counts
data/history/changes.csv               Changes between consecutive snapshots
```

Each annual snapshot contains normalized CSV tables plus provenance and validation metadata. Raw facility HTML is not committed to GitHub. The source-response SHA-256, retrieval timestamp, source page URL, source `lastModifiedAt` value when available, and parser version are retained in normalized records to support provenance and change auditing while limiting repository growth.

## Choosing the correct data table

The repository contains source listing tables, quality controlled coordinate tables, and derived provider entity tables. Select the table according to the research question and unit of analysis.

| Research purpose | Recommended file | Unit of analysis | Important interpretation |
|---|---|---|---|
| Count or map distinct providers | `data/derived/2026/providers.csv` | One derived provider entity | Use `provider_id`, `latitude`, and `longitude`. Birth Navi listings judged to represent the same provider have been consolidated. |
| Analyze Birth Navi listings | `data/quality/2026/facilities_final_coordinates.csv` | One Birth Navi listing | Use `final_latitude` and `final_longitude`. Several listing rows can refer to the same provider, so row counts are not provider counts. |
| Reproduce the source data as observed | `data/snapshots/2026/facilities.csv` | One source listing | The raw source coordinate fields are retained for audit purposes and are not recommended as the final GIS coordinates. |
| Analyze municipality linked postnatal care services | `data/derived/2026/municipality_postnatal_services.csv` | One municipality and provider relationship | The municipality represents a service or listing relationship. It does not necessarily represent the physical location of the provider. |
| Analyze services, fees, staffing, or facility characteristics | Detail tables under `data/snapshots/2026/` | One Birth Navi listing | Join tables with `birth_navi_id`. For provider level results, map listings through `data/derived/2026/provider_listing_map.csv` and state the aggregation rule. |
| Audit provider entity decisions | `data/derived/2026/provider_listing_map.csv`, `data/quality/2026/provider_entity_manual_decisions.csv`, and `data/quality/2026/provider_entity_manual_mapping.csv` | Listing mapping or review decision | Use these files to inspect and reproduce the consolidation of listings into provider entities. |
| Audit GSI geocoding | `data/quality/2026/gsi_address_representative_points.csv` | One geocoded public address | GSI coordinates are address representative points, not confirmed building entrances or service locations. |
| Conduct longitudinal analysis | Annual tables under `data/snapshots/YYYY/` and `data/history/` | One source listing per year | Do not assume that listing identifiers or provider groupings remain stable across years without verification. |

## Nationwide taxable-household postnatal-care dataset

The 2026 nationwide dataset covers all 47 prefectures and all 1,912
municipalities returned by the public Birth Navi municipality list. It combines
the validated Western Japan observations with observations collected for the
remaining 24 prefectures on 2026-10-28. Every request selected the resident
municipality in the 2026 relation table and `住民税課税世帯`.

| Research purpose | Recommended file | Unit of analysis | Interpretation |
|---|---|---|---|
| Analyze displayed fees | `data/derived/2026/nationwide_postnatal_taxable_fees.csv` | Resident municipality, provider, and displayed service option | Primary nationwide cost table. Exact amounts are separated from ranges, multiple tiers, missing values, contact-required entries, and unparsed text. |
| Restrict to providers located in the resident municipality | `data/derived/2026/nationwide_postnatal_taxable_fees.csv` | Same as above | Select `same_municipality_flag = 1`. A blank value means provider location could not be established, not that the provider is outside the municipality. |
| Retain all municipalities | `data/derived/2026/nationwide_municipality_postnatal_taxable_summary.csv` | One municipality | Includes all 1,912 municipalities. The 711 municipalities without a 2026 source relation are not classified as having no program or a zero fee. |
| Reproduce municipality selections | `data/snapshots/2026/nationwide_postnatal_taxable_relations.csv` | One resident municipality and Birth Navi listing | Retains 4,600 relations. Four source pages returned 404 and are marked `source_page_not_found`; 429 additional selections displayed no method-level details. |
| Reproduce displayed service text | `data/snapshots/2026/nationwide_postnatal_taxable_services.csv` | One displayed service option | Retains 6,493 method-level observations and their original fee and condition text. |
| Audit service-code differences | `data/quality/2026/nationwide_postnatal_taxable_service_discrepancies.csv` | One municipality-listing relation | Reports 946 differences from the earlier annual snapshot without deciding which observation is erroneous. |

The primary nationwide fee table contains 6,493 rows. It has 4,976 rows with
one conservatively normalized amount, 57 ranges, 628 multiple-price entries,
712 entries without a stated amount, 101 contact-required entries, and 19
unparsed descriptions. For resident-access analyses, retain all rows. For the
narrower analysis of providers physically located in the resident
municipality, use the 2,113 rows with `same_municipality_flag = 1` and report
the 4,101 rows whose provider municipality is unknown.

## Western Japan taxable-household postnatal-care dataset

The 2026 Western Japan dataset extends the validated Nara pilot to 23
prefectures: Shiga, Kyoto, Osaka, Hyogo, Nara, Wakayama, Tottori, Shimane,
Okayama, Hiroshima, Yamaguchi, Tokushima, Kagawa, Ehime, Kochi, Fukuoka, Saga,
Nagasaki, Kumamoto, Oita, Miyazaki, Kagoshima, and Okinawa. This operational
definition covers Kinki excluding Mie, Chugoku, Shikoku, Kyushu, and Okinawa.
Observations were collected on 2026-10-28 after selecting each resident
municipality represented in the 2026 source relations and `住民税課税世帯` in
the public Birth Navi display.

Use the following tables according to the analysis:

| Research purpose | Recommended file | Unit of analysis | Interpretation |
|---|---|---|---|
| Analyze displayed postnatal-care fees for taxable households | `data/derived/2026/western_japan_postnatal_taxable_fees.csv` | Resident municipality, provider, and displayed service option | The primary cost-analysis table. `fee_yen` is populated only when one amount can be normalized conservatively. Use `fee_min_yen` and `fee_max_yen` for ranges or multiple tiers, together with the original `fee_text`. |
| Restrict the analysis to providers located in the resident municipality | `data/derived/2026/western_japan_postnatal_taxable_fees.csv` | Same as above | Select `same_municipality_flag = 1`. Do not treat a blank flag as outside the municipality; it means that provider location could not be established from a standard facility listing. |
| Retain every municipality in the 23-prefecture scope | `data/derived/2026/western_japan_municipality_postnatal_taxable_summary.csv` | One municipality | All 756 municipalities returned by the public municipality list are retained. The 261 municipalities marked `no_relation_in_2026_snapshot` had no relation in the source table; this is not evidence of zero cost or absence of a municipal program. |
| Inspect a municipality-provider selection that displayed no service details | `data/snapshots/2026/western_japan_postnatal_taxable_relations.csv` | One resident municipality and Birth Navi listing | 193 of 1,953 selections displayed no method-level details after household selection. They are recorded as missing display information, not as zero cost. |
| Reproduce the displayed method-level text | `data/snapshots/2026/western_japan_postnatal_taxable_services.csv` | One displayed service option | Preserves fee, included items, maximum use, infant age, multiple-birth acceptance, sibling acceptance, notes, option order, and source service ID as displayed. |
| Audit differences from the earlier annual facility snapshot | `data/quality/2026/western_japan_postnatal_taxable_service_discrepancies.csv` | One municipality-listing relation | 417 of 1,953 relations have different service-type code sets. The table reports missing and unexpected codes without deciding that either observation is erroneous. |

The primary fee table contains 2,852 displayed service-option rows from 1,953
municipality-provider relations. It distinguishes exact amounts, ranges,
multiple price tiers, missing amounts, contact-required entries, and one
unparsed nonnumeric description. A range or multi-tier price is not reduced to
one point estimate. Source text remains available for alternative analytic
decisions. The original Nara files are retained as a stable validated subset;
their 59 relations and 96 service rows match the Nara rows in the Western Japan
dataset on the substantive fields.

For an analysis of services available to residents, retain all rows regardless
of `same_municipality_flag`. For the narrower question of providers physically
located in the resident municipality, select only `same_municipality_flag = 1`
and report the number excluded because provider location was unknown.

### Coordinate selection for spatial analysis

For provider level spatial analysis, use `data/derived/2026/providers.csv`. For listing level spatial analysis, use `data/quality/2026/facilities_final_coordinates.csv` and the `final_latitude` and `final_longitude` columns.

For fine scale distance, nearest provider, or travel time analysis:

1. Use records with available final coordinates and report the number and proportion excluded because coordinates were unavailable.
2. For the primary analysis, exclude GSI address representative points by selecting `coordinate_is_address_representative_point = 0` in `providers.csv`, or `final_coordinate_is_address_representative_point = 0` in the listing level table.
3. GSI points classified as `街区・番地等` may be added in a sensitivity analysis if their positional uncertainty is explicitly reported.
4. Points classified as `町字・丁目等`, `市区町村`, or `都道府県` should not be treated as precise provider locations for fine scale distance or travel time calculations.
5. Review `coordinate_semantics` and `coordinate_meaning` when they are populated. A registered or business base coordinate can differ from the actual service delivery location.

For regional distribution maps, GSI representative points may be included when their granularity is appropriate for the map scale. Distinguish them by source or granularity and report how their inclusion affects interpretation.

### Coordinate completeness in the 2026 data

- 4,649 of 5,638 listing records have final coordinates; 989 do not.
- 4,311 of 5,116 provider entities have coordinates; 805 do not.
- The listing level coordinate layer includes 266 GSI address representative points.

All 989 unresolved listing coordinates are municipality linked records with `facility_type_code = 100` whose addresses are not publicly displayed. Coordinate missingness is therefore structurally related to the listing type rather than random. Analyses of postnatal care access should report this limitation and should not silently remove unresolved records.

### Common interpretation errors

- Do not use the number of rows in `facilities.csv` or `facilities_final_coordinates.csv` as the number of distinct providers.
- Do not use raw `latitude` and `longitude` when the final coordinate fields are available.
- Do not interpret a municipality representative point as the physical location of a provider.
- Do not use municipality or prefecture representative points for fine scale distance or travel time calculations.
- Do not aggregate fees, staffing, beds, delivery volumes, or service counts across duplicate listings without a stated aggregation rule.
- Always report coordinate completeness and any precision based exclusion criteria.

## Provider entity layer and duplicate listings

A `birth_navi_id` is a **source listing ID**, not necessarily a unique physical provider ID. Birth Navi can contain several municipality-linked records for the same postnatal-care provider, while common facility names can also refer to genuinely different providers.

For provider-level analysis, use the derived 2026 entity layer under `data/derived/2026/`:

- `providers.csv`: conservatively deduplicated provider entities;
- `provider_listing_map.csv`: every Birth Navi listing mapped to its derived provider entity with linkage method/confidence;
- `municipality_postnatal_services.csv`: provider–municipality postnatal listing relations;
- `deduplication_review.csv`: any same-name groups that remain unresolved after automatic and manual review.

The 2026 source contains 5,638 retrievable listings. Automatic resolution followed by documented manual adjudication of 165 same-name groups produces 5,116 provider entities; 522 listing rows are collapsed into supported provider clusters and no reviewed same-name group remains pending. Confirmed same-name but distinct providers remain separate. The raw annual snapshot is never overwritten. Manual decisions and the listing-level mapping are published under `data/quality/2026/`.

See [docs/provider_entity_model.md](docs/provider_entity_model.md) for linkage rules and interpretation.

## Coordinate quality

Coordinates are provenance-tracked rather than silently geocoded. The annual Birth Navi snapshot is preserved as observed, while separate quality-control layers cross-check deterministic facility matches against MHLW Medical Information Net open data. Missing coordinates are supplemented from direct MHLW coordinate fields or independently public addresses under conservative identity/address rules. For 266 still-unresolved listings with a public facility or registered-base address, GSI Maps address search is used to assign an explicitly labelled address representative point. These points vary from block/address level to prefecture level and are not facility entrances or building centroids. Hidden Birth Navi information is never used to infer a point location. Outreach-only providers are still eligible when a registered or business base is independently public; such coordinates are labelled as provider-origin/base coordinates and must not be interpreted as the actual service-delivery point.

For 2026, 44 deterministic cross-source discrepancies greater than 500 m were manually reviewed by Ryo Horiike. Birth Navi was selected for 27 facilities and MHLW Medical Information Net for 17. The final layer contains coordinates for 4,649 of 5,638 listings, including 266 GSI address representative points; 989 listings remain unresolved. **For GIS and accessibility analyses, use `data/quality/2026/facilities_final_coordinates.csv` and its `final_latitude` / `final_longitude` fields**, not the raw snapshot coordinate columns. Filter or stratify GSI points using `final_coordinate_is_address_representative_point` and `gsi_representative_point_granularity` when positional precision affects the analysis.

See [docs/coordinate_quality.md](docs/coordinate_quality.md) and the outputs under `data/quality/2026/`.

## Longitudinal analysis

Annual snapshots are retained rather than overwritten. This allows analyses such as:

- annual increase/decrease in listed facilities;
- changes in prenatal, delivery, and postnatal-care service combinations;
- changes in reported delivery costs, prenatal-checkup costs, room charges, and painless-delivery costs;
- changes in staffing and bed resources;
- geographic changes in access to perinatal services.

`data/history/changes.csv` records field-level differences between consecutive annual snapshots. Because observations are annual, a detected change means that the value changed **sometime between the two annual observation dates**; it should not be interpreted as the exact date of change.

## Citation

When using these data in a paper, report, presentation, thesis, or other scholarly output, please cite **both** the G-CHAM Perinatal Database and the original MHLW Birth Navi source. Replace `YYYY` with the snapshot year actually used and add an access date where required by the citation style.

### APA 7th

> Horiike, R. (YYYY). *G-CHAM Perinatal Database: YYYY annual snapshot* [Data set]. GitHub. https://github.com/GISPHN/G-CHAM-Perinatal-Database

Source attribution:

> Ministry of Health, Labour and Welfare, Japan. (YYYY). *Birth Navi (出産なび)* [Data source]. https://birth-navi.mhlw.go.jp/

### Vancouver

> Horiike R. G-CHAM Perinatal Database: YYYY annual snapshot [dataset]. GitHub; YYYY [cited YYYY Mon DD]. Available from: https://github.com/GISPHN/G-CHAM-Perinatal-Database

Source attribution:

> Ministry of Health, Labour and Welfare, Japan. Birth Navi (出産なび) [Internet]. Tokyo: Ministry of Health, Labour and Welfare; [cited YYYY Mon DD]. Available from: https://birth-navi.mhlw.go.jp/

### Chicago Author-Date

> Horiike, Ryo. YYYY. “G-CHAM Perinatal Database: YYYY Annual Snapshot.” Dataset. GitHub. https://github.com/GISPHN/G-CHAM-Perinatal-Database.

Source attribution:

> Ministry of Health, Labour and Welfare, Japan. YYYY. “Birth Navi (出産なび).” https://birth-navi.mhlw.go.jp/.

### Harvard

> Horiike, R. (YYYY) *G-CHAM Perinatal Database: YYYY annual snapshot* [Data set]. Available at: https://github.com/GISPHN/G-CHAM-Perinatal-Database (Accessed: DD Month YYYY).

### BibTeX

```bibtex
@dataset{horiike_gcham_perinatal_YYYY,
  author    = {Ryo Horiike},
  title     = {G-CHAM Perinatal Database: YYYY annual snapshot},
  year      = {YYYY},
  publisher = {GitHub},
  url       = {https://github.com/GISPHN/G-CHAM-Perinatal-Database}
}
```

For transparent provenance in the Methods or Data Availability section, a useful wording is:

> Facility information was obtained from the Ministry of Health, Labour and Welfare's Birth Navi (出産なび) and processed into the G-CHAM Perinatal Database by Ryo Horiike.

## Interpretation cautions

- `postnatal_care_listed = 1` means that the facility is listed on Birth Navi as providing postnatal-care services; it does not establish municipality-specific eligibility.
- Prenatal-checkup costs are facility-reported amounts and are not municipality-subsidy-adjusted out-of-pocket costs.
- Site-provided or deterministic direct-source coordinates remain primary. GSI address representative points fill only otherwise unresolved records and must be analysed according to their recorded granularity and semantics.
- Missing values, explicit “none,” service unavailability, and information not displayed by the source should not be treated as equivalent without reference to the data dictionary.
- Values may reflect reporting lag at the source facility.

## Responsible collection

The workflow is intentionally conservative to minimize load on the MHLW service. Do not modify it to perform high-concurrency or high-frequency crawling. If `robots.txt`, site terms, response behavior, or the application schema changes, collection should be reviewed before resuming.

## Author

**Ryo Horiike**

G-CHAM (GIS-based Community Health Assessment Methods)
