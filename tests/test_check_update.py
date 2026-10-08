"""Isolated update checks: no real network, Git commands, or installs."""

from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import tempfile
import unittest
from unittest.mock import patch
import urllib.error


SPEC = importlib.util.spec_from_file_location(
    "check_update", Path(__file__).resolve().parents[1] / "scripts" / "check_update.py"
)
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


class UpdateCheckTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.local_version = "2026.10.08.1"
        self.now = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)
        self.clock = patch.object(checker, "_utc_now", return_value=self.now).start()
        self.addCleanup(patch.stopall)
        self.write_manifest()

    def manifest(self, version=None):
        return {
            "version": version or self.local_version,
            "repository": checker.REPOSITORY_URL,
            "branch": "main",
        }

    def write_manifest(self, version=None):
        (self.root / "version.json").write_text(
            json.dumps(self.manifest(version)), encoding="utf-8"
        )

    def run_with_remote(self, remote):
        with patch.object(checker, "_fetch_remote_manifest", return_value=remote):
            result = checker.check_update(self.root)
        json.dumps(result)
        return result

    def test_current_version(self):
        result = self.run_with_remote(self.manifest())
        self.assertEqual(result["status"], "up_to_date")
        self.assertEqual(result["local_version"], self.local_version)
        self.assertEqual(result["latest_version"], self.local_version)
        self.assertFalse(result["cache_used"])
        self.assertNotIn("update_command", result)

    def test_newer_release_and_zip_instructions(self):
        result = self.run_with_remote(self.manifest("2026.10.08.10"))
        self.assertEqual(result["status"], "update_available")
        self.assertEqual(result["download_url"], checker.DOWNLOAD_URL)
        self.assertIn("user-data", result["download_instructions"])
        self.assertNotIn("update_command", result)

    def test_git_command_quotes_special_characters_in_directory(self):
        self.root = self.root / "a'b $variable; & name"
        self.root.mkdir()
        self.write_manifest()
        (self.root / ".git").write_text("gitdir: elsewhere", encoding="utf-8")
        result = self.run_with_remote(self.manifest("2026.10.09.1"))
        if os.name == "nt":
            quoted = "'" + str(self.root.resolve()).replace("'", "''") + "'"
            self.assertEqual(result["update_command_shell"], "powershell")
            self.assertEqual(result["update_command"], f"git -C {quoted} pull --ff-only")
        else:
            self.assertEqual(
                shlex.split(result["update_command"]),
                ["git", "-C", str(self.root.resolve()), "pull", "--ff-only"],
            )

    def test_local_ahead_is_not_a_downgrade_recommendation(self):
        result = self.run_with_remote(self.manifest("2026.10.07.9"))
        self.assertEqual(result["status"], "local_ahead")
        self.assertNotIn("update_command", result)

    def test_invalid_remote_manifests_do_not_break_local_use(self):
        invalid = [
            None, [], {}, self.manifest("2026.10.09.1; run-code"),
            self.manifest("2026.10.09"),
            {**self.manifest(), "repository": "https://example.com/other"},
            {**self.manifest(), "branch": "other"},
            {**self.manifest(), "version": [1, 2, 3, 4]},
        ]
        for remote in invalid:
            with self.subTest(remote=remote):
                with patch.object(checker, "_fetch_remote_manifest", return_value=remote):
                    result = checker.check_update(self.root, force=True)
                self.assertEqual(result["status"], "check_failed")
                self.assertIsNone(result["latest_version"])

    def test_valid_cache_works_offline_and_expires_after_six_hours(self):
        self.run_with_remote(self.manifest("2026.10.09.1"))
        with patch.object(checker, "_fetch_remote_manifest", side_effect=OSError("offline")) as fetch:
            self.clock.return_value = self.now + timedelta(hours=5, minutes=59)
            cached = checker.check_update(self.root)
            self.assertEqual(cached["status"], "update_available")
            self.assertTrue(cached["cache_used"])
            fetch.assert_not_called()
            self.clock.return_value = self.now + timedelta(hours=6)
            expired = checker.check_update(self.root)
            self.assertEqual(expired["status"], "check_failed")
            self.assertFalse(expired["cache_used"])
            fetch.assert_called_once()

    def test_failed_check_is_cached_for_fifteen_minutes(self):
        with patch.object(checker, "_fetch_remote_manifest", side_effect=OSError("offline")) as fetch:
            first = checker.check_update(self.root)
            self.assertEqual(first["status"], "check_failed")
            self.clock.return_value = self.now + timedelta(minutes=14)
            self.assertTrue(checker.check_update(self.root)["cache_used"])
            self.assertEqual(fetch.call_count, 1)
            self.clock.return_value = self.now + timedelta(minutes=15)
            self.assertFalse(checker.check_update(self.root)["cache_used"])
            self.assertEqual(fetch.call_count, 2)

    def test_local_version_change_and_force_bypass_cache(self):
        self.run_with_remote(self.manifest("2026.10.09.1"))
        self.write_manifest("2026.10.09.1")
        with patch.object(checker, "_fetch_remote_manifest", return_value=self.manifest("2026.10.09.1")) as fetch:
            changed = checker.check_update(self.root)
            self.assertEqual(changed["status"], "up_to_date")
            self.assertFalse(changed["cache_used"])
            self.assertEqual(fetch.call_count, 1)
            forced = checker.check_update(self.root, force=True)
            self.assertFalse(forced["cache_used"])
            self.assertEqual(fetch.call_count, 2)

    def test_corrupt_cache_and_future_dates_trigger_a_fresh_check(self):
        cache_dir = self.root / "user-data"
        cache_dir.mkdir()
        malformed = [
            "not JSON", "[]",
            json.dumps({"schema_version": 1, "local_version": self.local_version, "status": []}),
            json.dumps({
                "schema_version": 1, "local_version": self.local_version,
                "latest_version": self.local_version, "status": "up_to_date",
                "checked_at": (self.now + timedelta(minutes=1)).isoformat(),
            }),
        ]
        for content in malformed:
            with self.subTest(content=content):
                (cache_dir / "update-cache.json").write_text(content, encoding="utf-8")
                result = self.run_with_remote(self.manifest())
                self.assertEqual(result["status"], "up_to_date")
                self.assertFalse(result["cache_used"])

    def test_cache_cannot_inject_commands_or_urls(self):
        self.run_with_remote(self.manifest("2026.10.09.1"))
        cache_path = self.root / "user-data" / "update-cache.json"
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        data.update(repository_url="https://example.com", update_command="run malicious code")
        cache_path.write_text(json.dumps(data), encoding="utf-8")
        result = checker.check_update(self.root)
        self.assertTrue(result["cache_used"])
        self.assertEqual(result["repository_url"], checker.REPOSITORY_URL)
        self.assertNotIn("update_command", result)

    def test_missing_or_corrupt_local_manifest_never_uses_network(self):
        local = self.root / "version.json"
        with patch.object(checker, "_fetch_remote_manifest") as fetch:
            for content in ("[]", "not-json", "{}"):
                local.write_text(content, encoding="utf-8")
                self.assertEqual(checker.check_update(self.root)["status"], "check_failed")
            local.unlink()
            self.assertEqual(checker.check_update(self.root)["status"], "check_failed")
            fetch.assert_not_called()

    def test_read_only_cache_write_failure_is_nonfatal(self):
        with patch.object(checker.tempfile, "NamedTemporaryFile", side_effect=PermissionError("read only")):
            result = self.run_with_remote(self.manifest())
        self.assertEqual(result["status"], "up_to_date")
        self.assertFalse((self.root / "user-data" / "update-cache.json").exists())

    def test_failed_atomic_cache_replace_cleans_up_temporary_file(self):
        with patch.object(checker.os, "replace", side_effect=PermissionError("read only")):
            result = self.run_with_remote(self.manifest())
        self.assertEqual(result["status"], "up_to_date")
        self.assertEqual(list((self.root / "user-data").iterdir()), [])

    def test_https_request_is_fixed_bounded_and_does_not_follow_redirects(self):
        payload = json.dumps(self.manifest()).encode("utf-8")
        with patch.object(checker.urllib.request, "build_opener") as build:
            build.return_value.open.return_value = io.BytesIO(payload)
            self.assertEqual(checker._fetch_remote_manifest(), self.manifest())
            request = build.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, checker.MANIFEST_URL)
            self.assertLessEqual(build.return_value.open.call_args.kwargs["timeout"], 4)
            self.assertIsInstance(build.call_args.args[0], checker._NoRedirect)
        handler = checker._NoRedirect()
        self.assertIsNone(handler.redirect_request(None, None, 302, "Found", {}, "http://example.com"))

    def test_oversized_or_invalid_remote_json_and_timeouts_fail_gracefully(self):
        for payload in (b"x" * (checker.MAX_JSON_BYTES + 1), b"not json", b"\xff"):
            with self.subTest(payload_length=len(payload)):
                with patch.object(checker.urllib.request, "build_opener") as build:
                    build.return_value.open.return_value = io.BytesIO(payload)
                    self.assertEqual(checker.check_update(self.root, force=True)["status"], "check_failed")
        for error in (TimeoutError(), urllib.error.URLError("offline"), checker.http.client.IncompleteRead(b"")):
            with self.subTest(error=type(error).__name__):
                with patch.object(checker, "_fetch_remote_manifest", side_effect=error):
                    self.assertEqual(checker.check_update(self.root, force=True)["status"], "check_failed")


if __name__ == "__main__":
    unittest.main()
