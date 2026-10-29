import csv
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data/snapshots/2026"
DERIVED = ROOT / "data/derived/2026"
QUALITY = ROOT / "data/quality/2026"
ALL_PREFECTURE_CODES = {f"{code:02d}" for code in range(1, 48)}


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


class NationwidePostnatalTaxableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.relations = read_csv(
            SNAPSHOT / "nationwide_postnatal_taxable_relations.csv"
        )
        cls.services = read_csv(
            SNAPSHOT / "nationwide_postnatal_taxable_services.csv"
        )
        cls.fees = read_csv(DERIVED / "nationwide_postnatal_taxable_fees.csv")
        cls.summary = read_csv(
            DERIVED / "nationwide_municipality_postnatal_taxable_summary.csv"
        )
        cls.discrepancies = read_csv(
            QUALITY / "nationwide_postnatal_taxable_service_discrepancies.csv"
        )

    def test_scope_and_relation_keys(self):
        self.assertEqual(len(self.relations), 4600)
        self.assertEqual(
            {r["resident_prefecture_code"] for r in self.relations},
            ALL_PREFECTURE_CODES,
        )
        keys = {
            (r["birth_navi_id"], r["resident_municipality_code"])
            for r in self.relations
        }
        self.assertEqual(len(keys), len(self.relations))
        self.assertTrue(all(
            r["household_type_code"] == "1" for r in self.relations
        ))

    def test_services_and_fee_rows(self):
        self.assertEqual(len(self.services), 6493)
        self.assertEqual(len(self.fees), len(self.services))
        keys = {
            (
                r["birth_navi_id"], r["resident_municipality_code"],
                r["postnatal_care_type_code"],
                r["postnatal_care_option_index"],
            )
            for r in self.services
        }
        self.assertEqual(len(keys), len(self.services))

    def test_fee_normalization_is_conservative(self):
        self.assertEqual(
            Counter(r["fee_normalization_status"] for r in self.fees),
            Counter({
                "exact_yen": 4842,
                "exact_yen_with_note": 134,
                "range_yen": 57,
                "multiple_tiers": 628,
                "not_stated": 712,
                "contact_required": 101,
                "unparsed": 19,
            }),
        )
        for row in self.fees:
            if row["fee_normalization_status"] not in {
                "exact_yen", "exact_yen_with_note"
            }:
                self.assertEqual(row["fee_yen"], "")

    def test_missing_and_not_found_are_not_zero(self):
        self.assertEqual(
            Counter(r["detail_status"] for r in self.relations),
            Counter({
                "services_displayed": 4167,
                "no_service_details_displayed_after_selection": 429,
                "source_page_not_found": 4,
            }),
        )
        service_keys = {
            (r["birth_navi_id"], r["resident_municipality_code"])
            for r in self.services
        }
        self.assertTrue(all(
            (r["birth_navi_id"], r["resident_municipality_code"])
            not in service_keys
            for r in self.relations
            if r["detail_status"] != "services_displayed"
        ))

    def test_all_municipalities_are_retained(self):
        self.assertEqual(len(self.summary), 1912)
        self.assertEqual(
            {r["resident_prefecture_code"] for r in self.summary},
            ALL_PREFECTURE_CODES,
        )
        self.assertEqual(
            Counter(r["source_relation_status"] for r in self.summary),
            Counter({"relation_present": 1201, "no_relation_in_2026_snapshot": 711}),
        )

    def test_provider_location_unknown_is_not_outside(self):
        self.assertEqual(
            Counter(r["same_municipality_flag"] or "unknown" for r in self.fees),
            Counter({"1": 2113, "0": 279, "unknown": 4101}),
        )
        for row in self.fees:
            if row["provider_location_status"] == "no_standard_facility_listing":
                self.assertEqual(row["same_municipality_flag"], "")

    def test_discrepancy_table_covers_relations(self):
        self.assertEqual(len(self.discrepancies), len(self.relations))
        self.assertEqual(
            Counter(r["discrepancy_status"] for r in self.discrepancies),
            Counter({"match": 3654, "snapshot_ui_difference": 946}),
        )

    def test_western_japan_is_a_substantive_subset(self):
        western_relations = read_csv(
            SNAPSHOT / "western_japan_postnatal_taxable_relations.csv"
        )
        nationwide = {
            (r["birth_navi_id"], r["resident_municipality_code"]): r
            for r in self.relations
            if int(r["resident_prefecture_code"]) >= 25
        }
        columns = [
            "facility_name_displayed", "eligibility_text", "overall_remarks",
            "observed_service_count", "detail_status", "source_last_modified_at",
        ]
        self.assertEqual(len(nationwide), len(western_relations))
        for old in western_relations:
            row = nationwide[(old["birth_navi_id"], old["resident_municipality_code"])]
            for column in columns:
                self.assertEqual(row[column], old[column])


if __name__ == "__main__":
    unittest.main()
