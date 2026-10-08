"""Release validation regressions using synthetic temporary public packages."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepare_release.py"
SPEC = importlib.util.spec_from_file_location("prepare_release", SCRIPT)
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "data").mkdir()
        (self.root / "scripts").mkdir()
        (self.root / "SKILL.md").write_text("# Food map\n", encoding="utf-8")
        (self.root / "scripts/query_food.py").write_text("print('ready')\n", encoding="utf-8")
        self.data = {
            "schema_version": 1,
            "metadata": {"imported_restaurant_count": 1, "expected_restaurant_count": None,
                         "access_status": "local_shared_snapshot"},
            "restaurants": [{"id": "restaurant-1", "dianping_shop_id": "shop-1",
                             "name": "Example restaurant", "sources": [],
                             "visited": None, "liked": None, "user_feedback": []}],
        }
        self.save_data()

    def save_data(self):
        (self.root / "data/favorites.json").write_text(
            json.dumps(self.data, ensure_ascii=False), encoding="utf-8")

    def test_release_roundtrip_increment_and_private_overlay_exclusion(self):
        manifest = release.prepare_release(self.root, "2026.10.08.1")
        self.assertEqual(manifest, release.check_release(self.root))
        self.assertNotIn("version.json", manifest["sha256"])
        overlay = self.root / "user-data"
        overlay.mkdir()
        (overlay / "preferences.json").write_text('{"token":"private"}', encoding="utf-8")
        self.assertEqual(manifest, release.check_release(self.root))
        for version in ("2026.10.08.1", "2026.10.08.0", "2026.10.07.999"):
            with self.subTest(version=version), self.assertRaises(release.ReleaseError):
                release.prepare_release(self.root, version)
        upgraded = release.prepare_release(self.root, "2026.10.08.2")
        self.assertEqual(upgraded["version"], "2026.10.08.2")
        self.assertEqual(upgraded, release.check_release(self.root))

    def test_calendar_date_and_format(self):
        for version in ("2026.02.29.1", "2026.13.01.1", "2026.10.8.1", "1.2.3",
                        "2026.10.08.-1", "2026.10.08.01", "2026.10.08.1\n", None):
            with self.subTest(version=version), self.assertRaises(release.ReleaseError):
                release.parse_version(version)
        self.assertEqual(release.parse_version("2028.02.29.1"), (2028, 2, 29, 1))

    def test_checksum_drift_added_and_removed_files(self):
        original = self.root / "SKILL.md"
        release.prepare_release(self.root, "2026.10.08.1")
        original.write_text("# Modified\n", encoding="utf-8")
        with self.assertRaisesRegex(release.ReleaseError, "checksums"):
            release.check_release(self.root)
        original.write_text("# Food map\n", encoding="utf-8")
        extra = self.root / "README.md"
        extra.write_text("Additional documentation\n", encoding="utf-8")
        with self.assertRaisesRegex(release.ReleaseError, "checksums"):
            release.check_release(self.root)
        release.prepare_release(self.root, "2026.10.08.2")
        extra.unlink()
        with self.assertRaisesRegex(release.ReleaseError, "checksums"):
            release.check_release(self.root)

    def test_canonical_hash_accepts_checkout_line_endings_and_bom(self):
        original = self.root / "SKILL.md"
        original.write_bytes(b"# Food map\r\nsecond line\r\n")
        manifest = release.prepare_release(self.root, "2026.10.08.1")
        original.write_bytes(b"# Food map\nsecond line\n")
        self.assertEqual(manifest, release.check_release(self.root))
        original.write_bytes(b"\xef\xbb\xbf# Food map\r\nsecond line\r\n")
        self.assertEqual(manifest, release.check_release(self.root))
        virtualenv = self.root / ".venv"
        virtualenv.mkdir()
        (virtualenv / "binary.exe").write_bytes(b"\x80\x81")
        self.assertEqual(manifest, release.check_release(self.root))

    def test_duplicate_ids_and_metadata_count(self):
        self.data["metadata"]["imported_restaurant_count"] = 2
        self.save_data()
        with self.assertRaisesRegex(release.ReleaseError, "count"):
            release.validate_and_hash(self.root)
        self.data["restaurants"].append(dict(self.data["restaurants"][0]))
        self.save_data()
        with self.assertRaisesRegex(release.ReleaseError, "duplicate.*id"):
            release.validate_and_hash(self.root)
        self.data["restaurants"][1]["id"] = "restaurant-2"
        self.save_data()
        with self.assertRaisesRegex(release.ReleaseError, "duplicate.*dianping_shop_id"):
            release.validate_and_hash(self.root)

    def test_personal_feedback_rejected_including_false(self):
        for field, value in (("visited", False), ("liked", True),
                             ("user_feedback", [{"comment": "private feedback"}])):
            with self.subTest(field=field):
                row = self.data["restaurants"][0]
                before = row[field]
                row[field] = value
                self.save_data()
                with self.assertRaisesRegex(release.ReleaseError, "personal"):
                    release.validate_and_hash(self.root)
                row[field] = before
        self.save_data()
        release.validate_and_hash(self.root)

    def test_public_content_scan_recursive_and_safe_errors(self):
        samples = [
            {"note": "C:\\Users\\Example\\private.txt"},
            {"note": "/home/example/private.txt"},
            {"note": "https://www.dianping.com/member/12345"},
            {"nested": [{"accessToken": "must-not-echo"}]},
            {"nested": [{"dianping_cookie": "must-not-echo"}]},
        ]
        for value in samples:
            with self.subTest(value=value):
                target = self.root / "references/deep/source.json"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(value), encoding="utf-8")
                with self.assertRaises(release.ReleaseError) as caught:
                    release.validate_and_hash(self.root)
                self.assertNotIn("must-not-echo", str(caught.exception))
                self.assertIn("references/deep/source.json", str(caught.exception))

    def test_invalid_structure_and_schema(self):
        for value in (True, 0, "1"):
            self.data["schema_version"] = value
            self.save_data()
            with self.subTest(value=value), self.assertRaises(release.ReleaseError):
                release.validate_and_hash(self.root)
        self.data["schema_version"] = 1
        self.data["restaurants"][0]["sources"] = "unexpected"
        self.save_data()
        with self.assertRaisesRegex(release.ReleaseError, "sources"):
            release.validate_and_hash(self.root)

    def test_manifest_identity_and_timezone_checked(self):
        manifest = release.prepare_release(self.root, "2026.10.08.1")
        for field, value in (("repository", "https://example.com/other"),
                             ("branch", "other"), ("released_at", "2026-10-08T10:00:00")):
            damaged = dict(manifest)
            damaged[field] = value
            (self.root / "version.json").write_text(json.dumps(damaged), encoding="utf-8")
            with self.subTest(field=field), self.assertRaises(release.ReleaseError):
                release.check_release(self.root)

    def test_manifest_personal_content_rejected(self):
        manifest = release.prepare_release(self.root, "2026.10.08.1")
        manifest["cookie"] = "must-not-echo"
        (self.root / "version.json").write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(release.ReleaseError, "credential-like"):
            release.check_release(self.root)


if __name__ == "__main__":
    unittest.main()
