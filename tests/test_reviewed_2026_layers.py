import csv
import importlib.util
import unittest
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUALITY = ROOT / "data/quality/2026"
DERIVED = ROOT / "data/derived/2026"


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


class Reviewed2026LayerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.final = read_csv(QUALITY / "facilities_final_coordinates.csv")
        cls.gsi = read_csv(QUALITY / "gsi_address_representative_points.csv")
        cls.decisions = read_csv(QUALITY / "provider_entity_manual_decisions.csv")
        cls.manual_map = read_csv(QUALITY / "provider_entity_manual_mapping.csv")
        cls.providers = read_csv(DERIVED / "providers.csv")
        cls.listing_map = read_csv(DERIVED / "provider_listing_map.csv")
        cls.pending = read_csv(DERIVED / "deduplication_review.csv")

    def test_coordinate_layer_counts_and_keys(self):
        self.assertEqual(len(self.final), 5638)
        self.assertEqual(len({r["birth_navi_id"] for r in self.final}), 5638)
        present = [r for r in self.final if r["final_latitude"] and r["final_longitude"]]
        self.assertEqual(len(present), 4649)
        self.assertEqual(len(self.final) - len(present), 989)

    def test_gsi_points_are_explicit_representative_points(self):
        self.assertEqual(len(self.gsi), 266)
        self.assertEqual(len({r["birth_navi_id"] for r in self.gsi}), 266)
        expected = {
            "街区・番地等": 10,
            "町字・丁目等": 231,
            "市区町村": 23,
            "都道府県": 2,
        }
        self.assertEqual(
            Counter(r["representative_point_granularity"] for r in self.gsi),
            expected,
        )
        final_by_id = {r["birth_navi_id"]: r for r in self.final}
        for source in self.gsi:
            result = final_by_id[source["birth_navi_id"]]
            self.assertEqual(result["final_latitude"], source["latitude"])
            self.assertEqual(result["final_longitude"], source["longitude"])
            self.assertEqual(result["final_coordinate_source"], "gsi_maps_address_search")
            self.assertEqual(result["final_coordinate_is_address_representative_point"], "1")
            self.assertEqual(
                result["gsi_representative_point_granularity"],
                source["representative_point_granularity"],
            )
            self.assertTrue(result["coordinate_meaning"])
            self.assertTrue(result["gsi_address_source_name"])
            self.assertTrue(result["gsi_address_source_url"])

    def test_gsi_points_are_not_identity_linkage_coordinates(self):
        spec = importlib.util.spec_from_file_location(
            "build_provider_entities",
            ROOT / "scripts/build_provider_entities.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        row = {
            "final_latitude": "35.0",
            "final_longitude": "135.0",
            "final_coordinate_is_address_representative_point": "1",
        }
        self.assertIsNone(module.coord_for_entity_resolution(row))

    def test_manual_provider_adjudication_is_fully_applied(self):
        self.assertEqual(len(self.decisions), 165)
        self.assertEqual(len({r["group_no"] for r in self.decisions}), 165)
        self.assertEqual(len(self.manual_map), 438)
        self.assertEqual(len({r["birth_navi_id"] for r in self.manual_map}), 438)
        self.assertTrue(all(r["review_status"] == "確認済み" for r in self.manual_map))

        output_by_id = {r["birth_navi_id"]: r for r in self.listing_map}
        for decision in self.manual_map:
            output = output_by_id[decision["birth_navi_id"]]
            self.assertEqual(output["provider_id"], decision["proposed_provider_id"])
            self.assertEqual(output["deduplication_method"], "manual_same_name_adjudication")
            self.assertEqual(output["deduplication_confidence"], "manual_confirmed")
            self.assertEqual(output["manual_review_group_no"], decision["group_no"])
            self.assertEqual(output["manual_review_verdict"], decision["verdict"])

    def test_provider_layer_counts_and_stable_ids(self):
        self.assertEqual(len(self.providers), 5116)
        self.assertEqual(len(self.listing_map), 5638)
        self.assertEqual(len(self.pending), 0)
        members = defaultdict(list)
        for row in self.listing_map:
            members[row["provider_id"]].append(int(row["birth_navi_id"]))
        self.assertEqual(len(members), 5116)
        for provider_id, ids in members.items():
            self.assertEqual(provider_id, f"GCP-{min(ids):05d}")


if __name__ == "__main__":
    unittest.main()
