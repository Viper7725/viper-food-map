#!/usr/bin/env python3
"""Check the official release manifest and report updates without installing them."""

import argparse
from datetime import datetime, timezone
import http.client
import json
import os
from pathlib import Path
import re
import shlex
import sys
import tempfile
import urllib.request


REPOSITORY_URL = "https://github.com/Viper7725/viper-food-map"
BRANCH = "main"
MANIFEST_URL = (
    "https://raw.githubusercontent.com/Viper7725/viper-food-map/main/version.json"
)
DOWNLOAD_URL = REPOSITORY_URL + "/archive/refs/heads/main.zip"
REQUEST_TIMEOUT_SECONDS = 3
MAX_JSON_BYTES = 16 * 1024
SUCCESS_CACHE_SECONDS = 6 * 60 * 60
FAILURE_CACHE_SECONDS = 15 * 60
VERSION_PATTERN = re.compile(r"[0-9]{1,9}(?:\.[0-9]{1,9}){3}\Z")
SUCCESS_STATUSES = {"up_to_date", "update_available", "local_ahead"}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Only read the fixed official HTTPS endpoint, without following redirects."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _utc_now():
    return datetime.now(timezone.utc)


def _version_parts(value):
    if not isinstance(value, str) or not VERSION_PATTERN.fullmatch(value):
        raise ValueError("version must contain four numeric components")
    return tuple(int(part) for part in value.split("."))


def _decode_json(content):
    if len(content) > MAX_JSON_BYTES:
        raise ValueError("JSON document exceeds the size limit")
    try:
        return json.loads(content.decode("utf-8-sig"))
    except (UnicodeError, ValueError, RecursionError) as error:
        raise ValueError("invalid JSON document") from error


def _read_json(path):
    with path.open("rb") as source:
        return _decode_json(source.read(MAX_JSON_BYTES + 1))


def _validate_manifest(manifest):
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be an object")
    _version_parts(manifest.get("version"))
    if manifest.get("repository") != REPOSITORY_URL:
        raise ValueError("manifest repository does not match the official repository")
    if manifest.get("branch") != BRANCH:
        raise ValueError("manifest branch does not match the official branch")
    return manifest["version"]


def _fetch_remote_manifest():
    request = urllib.request.Request(
        MANIFEST_URL,
        headers={"Accept": "application/json", "User-Agent": "viper-food-map-update-check"},
    )
    opener = urllib.request.build_opener(_NoRedirect())
    with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return _decode_json(response.read(MAX_JSON_BYTES + 1))


def _compare_versions(local_version, latest_version):
    local = _version_parts(local_version)
    latest = _version_parts(latest_version)
    if local < latest:
        return "update_available"
    if local > latest:
        return "local_ahead"
    return "up_to_date"


def _read_cache(path, local_version, now):
    try:
        cached = _read_json(path)
        if not isinstance(cached, dict) or cached.get("schema_version") != 1:
            return None
        if cached.get("local_version") != local_version:
            return None
        status = cached.get("status")
        if not isinstance(status, str):
            return None
        if status in SUCCESS_STATUSES:
            if _compare_versions(local_version, cached.get("latest_version")) != status:
                return None
            lifetime = SUCCESS_CACHE_SECONDS
        elif status == "check_failed" and cached.get("latest_version") is None:
            lifetime = FAILURE_CACHE_SECONDS
        else:
            return None
        checked_at = cached.get("checked_at")
        if not isinstance(checked_at, str):
            return None
        checked = datetime.fromisoformat(checked_at)
        if checked.tzinfo is None:
            return None
        age = (now - checked).total_seconds()
        if age < 0 or age >= lifetime:
            return None
        return cached
    except (OSError, ValueError, TypeError, OverflowError):
        return None


def _write_cache(path, result):
    """A read-only installation must still be usable when caching fails."""
    temporary_path = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        content = {"schema_version": 1}
        for key in ("status", "local_version", "latest_version", "checked_at"):
            content[key] = result[key]
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=".update-cache-", suffix=".tmp", delete=False,
        ) as destination:
            temporary_path = Path(destination.name)
            json.dump(content, destination, ensure_ascii=False, indent=2)
            destination.write("\n")
        os.replace(temporary_path, path)
    except (OSError, ValueError):
        pass
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def _make_result(root, status, local_version, latest_version, checked_at, cache_used):
    messages = {
        "up_to_date": "当前已是最新版本。",
        "update_available": (
            f"发现新版本 {latest_version}（本地 {local_version}）。"
            "建议更新；本次检查不会自动下载或覆盖文件。"
        ),
        "local_ahead": "本地版本高于公开仓库中的版本，无需降级。",
        "check_failed": "暂时无法确认最新版本；可继续使用本地数据，稍后重试更新检查。",
    }
    result = {
        "status": status,
        "local_version": local_version,
        "latest_version": latest_version,
        "checked_at": checked_at,
        "cache_used": cache_used,
        "repository_url": REPOSITORY_URL,
        "download_url": DOWNLOAD_URL,
        "message": messages[status],
    }
    if status == "update_available":
        result["download_instructions"] = (
            "下载最新 ZIP 并解压，备份并保留原安装目录中的 user-data 文件夹，"
            "再用新版程序和 data 文件替换旧版；不要覆盖或删除个人 user-data。"
        )
        try:
            git_installation = (root / ".git").exists()
        except OSError:
            git_installation = False
        if git_installation:
            if os.name == "nt":
                quoted_root = "'" + str(root).replace("'", "''") + "'"
                shell = "powershell"
            else:
                quoted_root = shlex.quote(str(root))
                shell = "sh"
            result["update_command"] = f"git -C {quoted_root} pull --ff-only"
            result["update_command_shell"] = shell
    return result


def check_update(skill_dir=None, force=False):
    """Return a JSON-safe update status; failures never prevent local queries.

    Successes are cached for six hours and failures for fifteen minutes. A local
    version change invalidates either cache. ``force=True`` bypasses the cache.
    Remote manifests are data only: no downloads are installed or executed.
    """
    now = _utc_now()
    checked_at = now.isoformat(timespec="seconds")
    root = None
    local_version = None
    try:
        root = Path(skill_dir).resolve() if skill_dir is not None else Path(__file__).resolve().parents[1]
        local_version = _validate_manifest(_read_json(root / "version.json"))
    except (OSError, ValueError, TypeError, RuntimeError):
        result = _make_result(root, "check_failed", None, None, checked_at, False)
        result["message"] = "本地 version.json 缺失或格式不正确，无法检查更新；可继续使用本地数据。"
        return result

    cache_path = root / "user-data" / "update-cache.json"
    if not force:
        cached = _read_cache(cache_path, local_version, now)
        if cached is not None:
            return _make_result(
                root, cached["status"], local_version, cached.get("latest_version"),
                cached["checked_at"], True,
            )
    try:
        latest_version = _validate_manifest(_fetch_remote_manifest())
        status = _compare_versions(local_version, latest_version)
    except (OSError, ValueError, http.client.HTTPException):
        latest_version = None
        status = "check_failed"
    result = _make_result(root, status, local_version, latest_version, checked_at, False)
    _write_cache(cache_path, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="check now, ignoring the cache")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(check_update(force=args.force), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
