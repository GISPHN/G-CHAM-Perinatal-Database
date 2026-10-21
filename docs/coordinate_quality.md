# Coordinate quality and provenance

Geographic coordinates are treated as research data with explicit provenance. The 2026 annual snapshot preserves the values displayed by Birth Navi; coordinate verification is published separately under `data/quality/2026/` so that source observations are not silently overwritten.

## Verification sources

The primary cross-source reference is the Ministry of Health, Labour and Welfare (MHLW) Medical Information Net open data dated 2026-06-01. Hospital, clinic, and maternity-home facility files contain direct latitude and longitude fields (`所在地座標（緯度）`, `所在地座標（経度）`).

No commercial geocoder is used for automatic coordinate completion. GSI Maps address search is used only for the documented 266-record manual completion layer described below.

## Conservative matching rules

A missing Birth Navi coordinate is filled in the derived file `facilities_verified_coordinates.csv` only when identity is deterministic:

1. normalized facility name is an exact match;
2. prefecture and municipality match;
3. the Birth Navi address is visible; and
4. either:
   - the full normalized address matches exactly, or
   - the address is a unique prefix/truncation match and the Birth Navi facility type is consistent with the MHLW source category.

Addresses that Birth Navi marks as hidden are never used to infer or publish a point coordinate from hidden information. However, an outreach-only or home-visit provider is still a geocoding target when a registered office, business base, or other provider base is independently and publicly documented. In that case, the coordinate represents the **provider origin/base**, not the actual service-delivery point.

## Outreach and home-visit providers

Outreach-only, home-visit, and mobile providers are not excluded from coordinate acquisition. Their registered office or publicly documented business base can be analytically useful as an approximate provider origin when studying geographic coverage, travel burden, or plausible service areas.

The database therefore separates **coordinate location** from **coordinate meaning**:

- `service_site_or_provider_base`: a fixed facility or provider base that is also a plausible service site;
- `registered_or_business_base_not_service_location`: an outreach/mobile provider's registered or business base; useful as an origin proxy but not a service-delivery point;
- `provider_base_with_outreach_service`: a provider with a fixed base and outreach activity;
- `provider_base_semantics_to_be_confirmed`: a provider whose base can be sought, but the operational meaning requires review.

For outreach providers, a point coordinate should be used only as a **proxy origin**. It should not by itself be interpreted as the provider's catchment boundary or as evidence that care is delivered at that point. Service-area analyses should, where possible, combine the provider-base coordinate with information on municipalities served, stated visit range, travel-time assumptions, or other operational coverage information.

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

The original Birth Navi snapshot contained 1,265 facilities with missing latitude or longitude. Ten missing coordinates were recovered from MHLW direct coordinate fields under the conservative rules above. A further 266 records with independently public facility or registered-base addresses received GSI Maps address-search representative points. The remaining 989 records have no publishable point under the adopted rules, including records whose Birth Navi address is hidden and for which no independently public base was established.

The 266 GSI results comprise 10 block/address-level, 231 neighbourhood/chome-level, 23 municipality-level, and 2 prefecture-level representative points. These are address-search representatives, not verified entrances, building centroids, or observed service-delivery locations. Municipality- and prefecture-level points are suitable only for coarse visualization or sensitivity analysis and should not be used for fine-scale distance or accessibility estimates. Every result retains the public address source, query, returned title, granularity, query strategy, retrieval date, query URL, location model, and coordinate semantics in `gsi_address_representative_points.csv` and the final coordinate layer.

The repository stores the retrieved results rather than calling the search endpoint during each build. GSI states that this dynamic search function is intended mainly for GSI Maps, is not guaranteed to remain continuously available, and may change without notice; the same official explanation states that address searches use the University of Tokyo CSIS simple geocoding service. See [GSI Maps issue 29](https://github.com/gsi-cyberjapan/gsimaps/issues/29). The stored retrieval date and query URL are therefore essential provenance fields.

Cross-source checking identified 44 deterministic matches where Birth Navi and MHLW Medical Information Net coordinates differed by more than 500 m. These 44 cases were manually reviewed by Ryo Horiike on 2026-10-05. The adjudication selected the Birth Navi coordinate for 27 facilities and the MHLW Medical Information Net coordinate for 17 facilities.

The manual decisions are preserved in `coordinate_manual_review.csv`. They are applied only in the derived analysis layer `facilities_final_coordinates.csv`; the original annual Birth Navi snapshot remains unchanged.

For GIS and accessibility analyses, use:

- `facilities_final_coordinates.csv`
- `final_latitude`
- `final_longitude`
- `final_coordinate_source`
- `final_coordinate_status`

The final layer contains coordinates for 4,649 of 5,638 retrievable facilities; 989 remain unresolved. No coordinate is inferred from a Birth Navi-hidden address alone.

Supporting audit files:

- `coordinate_final_summary.json`
- `coordinate_manual_review.csv`
- `gsi_address_representative_points.csv`
- `coordinate_verification_summary.json`
- `coordinate_verification_candidates.csv`
- `facilities_verified_coordinates.csv`

The MHLW open-data documentation itself notes that reported facility information may be outdated or contain reporting errors. Therefore, source agreement increases confidence, while source disagreement is explicitly resolved by documented manual review rather than silently overwritten.
