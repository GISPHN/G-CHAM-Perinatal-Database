import csv
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data/snapshots/2026"
DERIVED = ROOT / "data/derived/2026"
QUALITY = ROOT / "data/quality/2026"

WESTERN_PREFECTURE_CODES = {
    f"{code:02d}" for code in range(25, 48)
}


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


class WesternJapanPostnatalTaxableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.relations = read_csv(
            SNAPSHOT / "western_japan_postnatal_taxable_relations.csv"
        )
        cls.services = read_csv(
            SNAPSHOT / "western_japan_postnatal_taxable_services.csv"
        )
        cls.fees = read_csv(
            DERIVED / "western_japan_postnatal_taxable_fees.csv"
        )
        cls.summary = read_csv(
            DERIVED / "western_japan_municipality_postnatal_taxable_summary.csv"
        )
        cls.discrepancies = read_csv(
            QUALITY
            / "western_japan_postnatal_taxable_service_discrepancies.csv"
        )

    def test_scope_and_relation_keys(self):
        self.assertEqual(len(self.relations), 1953)
        self.assertEqual(
            {r["resident_prefecture_code"] for r in self.relations},
            WESTERN_PREFECTURE_CODES,
        )
        keys = {
            (r["birth_navi_id"], r["resident_municipality_code"])
            for r in self.relations
        }
        self.assertEqual(len(keys), len(self.relations))
        self.assertTrue(
            all(r["household_type_code"] == "1" for r in self.relations)
        )

    def test_service_keys_and_derived_rows(self):
        self.assertEqual(len(self.services), 2852)
        keys = {
            (
                r["birth_navi_id"], r["resident_municipality_code"],
                r["postnatal_care_type_code"],
                r["postnatal_care_option_index"],
            )
            for r in self.services
        }
        self.assertEqual(len(keys), len(self.services))
        self.assertEqual(len(self.fees), len(self.services))

    def test_nara_subset_matches_validated_pilot(self):
        old_relations = read_csv(
            SNAPSHOT / "nara_postnatal_taxable_relations.csv"
        )
        old_services = read_csv(
            SNAPSHOT / "nara_postnatal_taxable_services.csv"
        )
        new_relations = {
            (r["birth_navi_id"], r["resident_municipality_code"]): r
            for r in self.relations if r["resident_prefecture_code"] == "29"
        }
        relation_columns = [
            "facility_name_displayed", "eligibility_text", "overall_remarks",
            "observed_service_count", "detail_status", "source_last_modified_at",
        ]
        self.assertEqual(len(new_relations), len(old_relations))
        for old in old_relations:
            key = (old["birth_navi_id"], old["resident_municipality_code"])
            new = new_relations[key]
            for column in relation_columns:
                self.assertEqual(new[column], old[column], (key, column))

        new_services = {
            (
                r["birth_navi_id"], r["resident_municipality_code"],
                r["postnatal_care_type_code"],
            ): r
            for r in self.services if r["resident_prefecture_code"] == "29"
        }
        service_columns = [
            "facility_name_displayed", "postnatal_care_type", "fee_text",
            "fee_includes_text", "max_use_text", "eligible_infant_age_text",
            "multiple_birth_acceptance_text", "sibling_acceptance_text",
            "service_notes_text", "source_last_modified_at",
        ]
        self.assertEqual(len(new_services), len(old_services))
        for old in old_services:
            key = (
                old["birth_navi_id"], old["resident_municipality_code"],
                old["postnatal_care_type_code"],
            )
            new = new_services[key]
            for column in service_columns:
                self.assertEqual(new[column], old[column], (key, column))

    def test_missing_display_is_not_zero(self):
        no_display = [
            r for r in self.relations
            if r["detail_status"]
            == "no_service_details_displayed_after_selection"
        ]
        service_relation_keys = {
            (r["birth_navi_id"], r["resident_municipality_code"])
            for r in self.services
        }
        self.assertTrue(no_display)
        self.assertTrue(all(
            (r["birth_navi_id"], r["resident_municipality_code"])
            not in service_relation_keys
            for r in no_display
        ))

    def test_fee_normalization_is_conservative(self):
        allowed = {
            "exact_yen", "exact_yen_with_note", "range_yen",
            "multiple_tiers", "not_stated", "contact_required", "unparsed",
        }
        self.assertTrue(
            all(r["fee_normalization_status"] in allowed for r in self.fees)
        )
        for row in self.fees:
            status = row["fee_normalization_status"]
            if status in {"range_yen", "multiple_tiers"}:
                self.assertEqual(row["fee_yen"], "")
            if status in {"not_stated", "contact_required", "unparsed"}:
                self.assertEqual(row["fee_yen"], "")
        self.assertEqual(
            Counter(r["fee_normalization_status"] for r in self.fees),
            Counter({
                "exact_yen": 2101,
                "exact_yen_with_note": 51,
                "range_yen": 44,
                "multiple_tiers": 306,
                "not_stated": 310,
                "contact_required": 39,
                "unparsed": 1,
            }),
        )

    def test_all_municipalities_are_retained(self):
        self.assertEqual(len(self.summary), 756)
        self.assertEqual(
            len({r["resident_municipality_code"] for r in self.summary}),
            len(self.summary),
        )
        self.assertEqual(
            {r["resident_prefecture_code"] for r in self.summary},
            WESTERN_PREFECTURE_CODES,
        )
        self.assertTrue(any(
            r["source_relation_status"] == "no_relation_in_2026_snapshot"
            for r in self.summary
        ))
        self.assertEqual(
            {
                r["cost_collection_status"] for r in self.summary
            },
            {
                "service_rows_collected",
                "no_service_details_displayed",
                "no_relation_in_2026_snapshot",
            },
        )

    def test_location_unknown_is_not_encoded_as_outside(self):
        self.assertTrue(
            all(r["same_municipality_flag"] in {"", "0", "1"} for r in self.fees)
        )
        for row in self.fees:
            if row["provider_location_status"] == "no_standard_facility_listing":
                self.assertEqual(row["same_municipality_flag"], "")

    def test_discrepancy_table_covers_every_relation(self):
        self.assertEqual(len(self.discrepancies), len(self.relations))
        status = Counter(r["discrepancy_status"] for r in self.discrepancies)
        self.assertEqual(status, Counter({
            "match": 1536,
            "snapshot_ui_difference": 417,
        }))


if __name__ == "__main__":
    unittest.main()
