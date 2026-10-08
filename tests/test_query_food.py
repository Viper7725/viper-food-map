import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import query_food


class QueryTests(unittest.TestCase):
    def test_feedback_overlay_preserves_shared_snapshot_and_identity(self):
        original = [{"id": "shop-1", "name": "共享店名", "visited": None, "liked": None}]
        with tempfile.TemporaryDirectory() as directory:
            overlay = Path(directory) / "feedback.json"
            overlay.write_text(json.dumps({"restaurants": {"shop-1": {
                "visited": True, "liked": False, "name": "不允许覆盖",
                "user_feedback": [{"text": "去过", "recorded_at": "2026-10-08"}]
            }}}), encoding="utf-8")
            result = query_food.apply_feedback(original, overlay)
        self.assertIsNone(original[0]["visited"])
        self.assertEqual(result[0]["name"], "共享店名")
        self.assertIs(result[0]["visited"], True)
        self.assertIs(result[0]["liked"], False)

    def test_bad_feedback_is_not_silently_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            overlay = Path(directory) / "feedback.json"
            overlay.write_text('{"restaurants":{"shop-1":{"visited":"yes"}}}', encoding="utf-8")
            with self.assertRaises(ValueError):
                query_food.apply_feedback([{"id": "shop-1"}], overlay)

    def test_offline_query_filter_and_pagination_from_another_directory(self):
        data = {"restaurants": [
            {"id": "1", "name": "甲烤肉", "city": "杭州", "visited": None},
            {"id": "2", "name": "乙烧烤", "city": "杭州市", "visited": None},
            {"id": "3", "name": "丙烤肉", "city": "杭州湾", "visited": None},
        ]}
        with tempfile.TemporaryDirectory() as directory:
            data_path = Path(directory) / "favorites.json"
            data_path.write_text(json.dumps(data), encoding="utf-8")
            result = subprocess.run([
                sys.executable, str(ROOT / "scripts" / "query_food.py"),
                "--data", str(data_path), "--city", "杭州市", "--keyword", "烤肉",
                "--keyword", "烧烤", "--offset", "1", "--limit", "1", "--no-update-check"
            ], cwd=directory, capture_output=True, text=True, encoding="utf-8", check=True)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["total_matches"], 2)
        self.assertEqual(payload["restaurants"][0]["id"], "2")
        self.assertEqual(payload["returned_count"], 1)
        self.assertEqual(payload["update"]["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
