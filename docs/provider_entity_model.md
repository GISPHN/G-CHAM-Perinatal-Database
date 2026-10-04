# Provider entity resolution and municipality-linked postnatal listings

## Why this layer exists

A `birth_navi_id` is treated as a **Birth Navi listing identifier**, not automatically as a unique physical facility/provider identifier.

The 2026 Birth Navi snapshot contains multiple records with the same provider name. This occurs particularly among `facility_type_code = 100` records used for postnatal-care listings. A single provider can therefore appear under several municipality-specific Birth Navi records. Conversely, common names such as "ひまわり助産院" can refer to genuinely different providers in different places.

For this reason, the raw annual snapshot remains untouched and a separate derived entity layer is created.

## Derived tables

### providers.csv

One row per conservatively resolved provider entity.

Key fields:

- `provider_id`: derived G-CHAM provider identifier, based on the minimum Birth Navi ID in the resolved cluster.
- `representative_birth_navi_id`: source listing chosen as the representative record.
- `listing_count`: number of Birth Navi listings linked to the provider.
- `standard_facility_listing_count`: number of type 1–5 facility listings in the entity.
- `municipality_linked_type100_listing_count`: number of type-100 municipality-linked listings.
- `birth_navi_ids`: all source listing IDs retained for provenance.
- `latitude` / `longitude`: representative final coordinate from the provenance-aware coordinate layer.
- `coordinate_conflict_over_500m`: flag for provider clusters whose member coordinates still disagree materially.

### provider_listing_map.csv

One row per Birth Navi listing. This table maps every `birth_navi_id` to a derived `provider_id`.

It also records:

- source municipality,
- listing role,
- deduplication method,
- deduplication confidence,
- source URL.

This table is the audit trail between the raw snapshot and the provider entity layer.

### municipality_postnatal_services.csv

One row per Birth Navi postnatal listing/provider–municipality relation.

The municipality fields refer to the **municipality represented by the Birth Navi listing**, not necessarily the physical location of the provider. This is intentional: a provider based in one municipality may be available through another municipality's postnatal-care program.

This relation table should be used when analysing municipality–provider networks, service availability, or possible outreach coverage.

### deduplication_review.csv

Same-name groups that still map to more than one provider entity are exported for manual review. These records are deliberately **not** merged automatically.

## Automatic linkage rules

Automatic entity linkage is deliberately conservative. Strong links include:

1. the same non-empty MHLW official source entity ID;
2. the same canonical provider name and exact public address;
3. the same canonical provider name and exact public telephone number;
4. the same canonical provider name and final coordinates within 100 m.

For municipality-linked type-100 records, an additional constrained rule is permitted:

- exact non-generic name,
- same prefecture,
- at least one independent identifier/location item is available somewhere in the group, and
- all available phone/address/source-ID/coordinate evidence is non-conflicting.

Identifier-empty type-100 records may also attach to a single already-supported provider cluster within the same prefecture.

Generic labels such as `個人助産師`, `個人事業主助産師`, `在宅助産師`, and `出張専業助産師` are never merged by name-only propagation.

When two records both have final coordinates and are more than 1 km apart, phone/address/name-based propagation is blocked unless the same official MHLW source entity ID establishes identity.

## 2026 result

The 2026 source snapshot contains **5,638 retrievable Birth Navi listings**. Conservative entity resolution produces **5,178 provider entities**, collapsing **460 listing rows** into already-supported provider entities.

- 374 provider entities contain more than one Birth Navi listing.
- The largest resolved provider cluster contains 9 listings.
- 3,178 source records are type-100 listings.
- 4,600 postnatal provider–municipality listing relations are retained.
- 165 same-name groups still contain multiple provider entities and remain in `deduplication_review.csv`.

The derived count of 5,178 should therefore be interpreted as a **conservatively deduplicated provider count**, not a final claim that every unresolved listing represents a separate physical provider. Manual resolution of the review table can reduce residual over-counting without risking false merges.

## Example

`tanagocoro-miroku みろく助産院` appears in multiple municipality-linked Birth Navi records in Fukuoka Prefecture. The derived layer links the compatible records to one provider entity while preserving every municipality listing in `municipality_postnatal_services.csv`.

In contrast, `ひまわり助産院` occurs in multiple prefectures with different addresses and telephone numbers. Those records remain separate provider entities.

## Analytical use

For physical/provider-level GIS analysis, use `providers.csv`.

For raw-source auditing or reconstruction, use `provider_listing_map.csv` together with the annual snapshot.

For municipality-level postnatal-care availability and network analysis, use `municipality_postnatal_services.csv`.

For sensitivity analysis of unresolved duplicates, use `deduplication_review.csv`.
