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

**Municipality-dependent information is intentionally excluded from the initial implementation.** This includes municipality-specific prenatal-checkup subsidies, postnatal-care eligibility, household-category fees, and municipality-specific application procedures. Therefore, a facility being listed as providing postnatal care does **not** mean that every municipality resident can use that facility.

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

## Coordinate quality

Coordinates are provenance-tracked rather than silently geocoded. The annual Birth Navi snapshot is preserved as observed, while a separate verified coordinate layer cross-checks deterministic facility matches against MHLW Medical Information Net open data. Missing coordinates are supplemented only from direct MHLW coordinate fields under conservative identity/address rules; hidden Birth Navi addresses are never used to infer a point location. Material disagreement between official sources is flagged for review rather than automatically overwritten.

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
- Site-provided coordinates are retained as the primary geographic coordinates; the project does not re-geocode addresses as its primary method.
- Missing values, explicit “none,” service unavailability, and information not displayed by the source should not be treated as equivalent without reference to the data dictionary.
- Values may reflect reporting lag at the source facility.

## Responsible collection

The workflow is intentionally conservative to minimize load on the MHLW service. Do not modify it to perform high-concurrency or high-frequency crawling. If `robots.txt`, site terms, response behavior, or the application schema changes, collection should be reviewed before resuming.

## Author

**Ryo Horiike**

G-CHAM (GIS-based Community Health Assessment Methods)
