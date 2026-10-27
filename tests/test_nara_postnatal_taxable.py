import csv
import importlib.util
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data/snapshots/2026"
DERIVED = ROOT / "data/derived/2026"
QUALITY = ROOT / "data/quality/2026"


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


class NaraPostnatalTaxableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.relations = read_csv(
            SNAPSHOT / "nara_postnatal_taxable_relations.csv"
        )
        cls.services = read_csv(
            SNAPSHOT / "nara_postnatal_taxable_services.csv"
        )
        cls.fees = read_csv(DERIVED / "nara_postnatal_taxable_fees.csv")
        cls.summary = read_csv(
            DERIVED / "nara_municipality_postnatal_taxable_summary.csv"
        )
        cls.discrepancies = read_csv(
            QUALITY / "nara_postnatal_taxable_service_discrepancies.csv"
        )

    def test_relation_and_service_keys(self):
        self.assertEqual(len(self.relations), 59)
        relation_keys = {
            (r["birth_navi_id"], r["resident_municipality_code"])
            for r in self.relations
        }
        self.assertEqual(len(relation_keys), 59)
        self.assertEqual(len(self.services), 96)
        service_keys = {
            (
                r["birth_navi_id"], r["resident_municipality_code"],
                r["postnatal_care_type_code"],
            )
            for r in self.services
        }
        self.assertEqual(len(service_keys), 96)
        self.assertEqual(len(self.fees), 96)

    def test_scope_is_nara_taxable_households(self):
        self.assertTrue(
            all(r["resident_prefecture_code"] == "29" for r in self.relations)
        )
        self.assertTrue(
            all(r["household_type_code"] == "1" for r in self.relations)
        )
        self.assertTrue(
            all(r["household_type"] == "住民税課税世帯" for r in self.relations)
        )

    def test_no_display_is_not_encoded_as_zero(self):
        no_display = [
            r for r in self.relations
            if r["detail_status"] == "no_service_details_displayed_after_selection"
        ]
        self.assertEqual(len(no_display), 3)
        self.assertEqual(
            {r["birth_navi_id"] for r in no_display},
            {"11248", "14375", "14379"},
        )
        service_ids = {r["birth_navi_id"] for r in self.services}
        self.assertTrue(all(r["birth_navi_id"] not in service_ids for r in no_display))

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
                self.assertTrue(row["fee_min_yen"])
                self.assertTrue(row["fee_max_yen"])
            if status in {"not_stated", "contact_required", "unparsed"}:
                self.assertEqual(row["fee_yen"], "")

    def test_all_nara_municipalities_are_retained(self):
        self.assertEqual(len(self.summary), 39)
        self.assertEqual(
            len({r["resident_municipality_code"] for r in self.summary}), 39
        )
        status = Counter(r["source_relation_status"] for r in self.summary)
        self.assertEqual(status["relation_present"], 20)
        self.assertEqual(status["no_relation_in_2026_snapshot"], 19)
        for row in self.summary:
            if row["source_relation_status"] == "no_relation_in_2026_snapshot":
                self.assertEqual(row["relation_count"], "0")
                self.assertTrue(row["missing_reason"])

    def test_location_flag_does_not_assume_type100_location(self):
        self.assertTrue(
            all(r["same_municipality_flag"] in {"", "0", "1"} for r in self.fees)
        )
        for row in self.fees:
            if row["provider_location_status"] == "no_standard_facility_listing":
                self.assertEqual(row["same_municipality_flag"], "")

    def test_snapshot_ui_differences_are_published(self):
        self.assertEqual(len(self.discrepancies), 59)
        status = Counter(r["discrepancy_status"] for r in self.discrepancies)
        self.assertEqual(status["match"], 40)
        self.assertEqual(status["snapshot_ui_difference"], 19)

    def test_normalizer_examples(self):
        spec = importlib.util.spec_from_file_location(
            "build_nara_postnatal_taxable",
            ROOT / "scripts/build_nara_postnatal_taxable.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.normalize_fee("１０００円")["fee_yen"], "1000")
        ranged = module.normalize_fee("400～1,250円（別途食費代）")
        self.assertEqual(ranged["fee_normalization_status"], "range_yen")
        self.assertEqual(ranged["fee_min_yen"], "400")
        self.assertEqual(ranged["fee_max_yen"], "1250")
        self.assertEqual(ranged["fee_yen"], "")


if __name__ == "__main__":
    unittest.main()
