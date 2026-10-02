# Coordinate quality and provenance

Geographic coordinates are treated as research data with explicit provenance. The 2026 annual snapshot preserves the values displayed by Birth Navi; coordinate verification is published separately under `data/quality/2026/` so that source observations are not silently overwritten.

## Verification sources

The primary cross-source reference is the Ministry of Health, Labour and Welfare (MHLW) Medical Information Net open data dated 2026-06-01. Hospital, clinic, and maternity-home facility files contain direct latitude and longitude fields (`所在地座標（緯度）`, `所在地座標（経度）`).

No commercial geocoder is used for automatic coordinate completion.

## Conservative matching rules

A missing Birth Navi coordinate is filled in the derived file `facilities_verified_coordinates.csv` only when identity is deterministic:

1. normalized facility name is an exact match;
2. prefecture and municipality match;
3. the Birth Navi address is visible; and
4. either:
   - the full normalized address matches exactly, or
   - the address is a unique prefix/truncation match and the Birth Navi facility type is consistent with the MHLW source category.

Addresses that Birth Navi marks as hidden are never used to infer or publish a point coordinate.

## Coordinate quality states

The derived file includes `coordinate_quality_status`:

- `birth_navi_crosschecked_mhlw_within_100m`: Birth Navi coordinate and deterministic MHLW match differ by at most 100 m.
- `birth_navi_crosschecked_mhlw_100_500m`: cross-source difference is >100 m and <=500 m.
- `birth_navi_cross_source_discrepant_gt500m`: deterministic sources disagree by >500 m; requires review and is not automatically overwritten.
- `birth_navi_not_crosschecked`: Birth Navi coordinate is retained but no deterministic MHLW identity match was established.
- `mhlw_direct_exact_identity_full_visible_address`: Birth Navi coordinate was missing and a direct MHLW coordinate was added after an exact identity/full-address match.
- `mhlw_direct_exact_identity_truncated_visible_address_type_consistent`: Birth Navi coordinate was missing; a direct MHLW coordinate was added after exact name/prefecture/municipality identity, a unique visible address-prefix match, and facility-type/source-category agreement.
- `missing_hidden_address_not_inferred`: location is intentionally left unresolved because the Birth Navi address is hidden.
- `missing_unresolved`: no sufficiently strong direct-source match was established.

## 2026 findings

The original Birth Navi snapshot contained 1,265 facilities with missing latitude or longitude. Ten missing coordinates were recovered from the MHLW direct coordinate fields under the conservative rules above; 1,255 remain unresolved. Of the original missing records, 989 have the Birth Navi address hidden and are intentionally not point-geocoded.

Cross-source checking also identified deterministic matches where the two official sources disagree materially. These records are retained with the Birth Navi coordinate but flagged for review rather than silently replaced. See:

- `coordinate_verification_summary.json`
- `coordinate_discrepancies_over_500m.csv`
- `facilities_verified_coordinates.csv`

The MHLW open-data documentation itself notes that reported facility information may be outdated or contain reporting errors. Therefore, agreement between official sources increases confidence, whereas disagreement is treated as a quality-control signal rather than resolved automatically.
