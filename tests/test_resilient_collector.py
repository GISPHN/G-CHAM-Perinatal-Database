import csv
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from birth_navi_collector_v2 import ResilientFetcher


class AllowAllRobots:
    def can_fetch(self, user_agent, url):
        return True


class FakeResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text
        self.ok = 200 <= status_code < 400

    def __bool__(self):
        return self.ok


class FakeSession:
    def __init__(self, response):
        self.response = response

    def get(self, *args, **kwargs):
        return self.response


class ResilientCollectorTests(unittest.TestCase):
    def test_404_is_recorded_and_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = ResilientFetcher(Path(tmp), "test@example.org", delay=0, jitter=0)
            f.robots = AllowAllRobots()
            f.session = FakeSession(FakeResponse(404))
            f.sleep = lambda: None

            result = f.fetch(11639)
            self.assertEqual(result["__retrieval_status__"], "http_404")

            path = Path(tmp) / "tables" / "collection_status.csv"
            self.assertTrue(path.exists())
            with path.open("r", encoding="utf-8-sig", newline="") as h:
                rows = list(csv.DictReader(h))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["birth_navi_id"], "11639")
            self.assertEqual(rows[0]["http_status"], "404")
            self.assertEqual(rows[0]["retrieval_status"], "http_404")

    def test_429_remains_a_safety_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = ResilientFetcher(Path(tmp), "test@example.org", delay=0, jitter=0)
            f.robots = AllowAllRobots()
            f.session = FakeSession(FakeResponse(429))
            f.sleep = lambda: None

            with self.assertRaises(RuntimeError):
                f.fetch(11639)


if __name__ == "__main__":
    unittest.main()
