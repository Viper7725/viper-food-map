#!/usr/bin/env python3
"""Validate a public food-map package and prepare or check its release manifest."""

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile


REPOSITORY = "https://github.com/Viper7725/viper-food-map"
BRANCH = "main"
EXCLUDED_DIRS = {".git", "user-data", "tests", "__pycache__", ".pytest_cache", ".venv"}
EXCLUDED_FILES = {"version.json"}
VERSION_PATTERN = re.compile(r"([0-9]{4})\.([0-9]{2})\.([0-9]{2})\.(0|[1-9][0-9]*)\Z")
LOCAL_PATH = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]"
    r"|(?<![A-Za-z0-9])[\\/](?:Users|home|tmp|var|etc|mnt|Volumes|private|root)[\\/]"
    r"|\\\\[A-Za-z0-9_.-]+\\[A-Za-z0-9_.-]+"
)
ACCOUNT_URL = re.compile(
    r"https?://(?:[A-Za-z0-9-]+\.)*dianping\.com/"
    r"(?:member|user|mylist)(?:[/?.#]|$)", re.IGNORECASE
)
SENSITIVE_KEYS = {
    "password", "passwd", "secret", "token", "accesstoken", "refreshtoken",
    "authorization", "apikey", "accesskey", "privatekey", "clientsecret",
    "cookie", "cookies", "sessionid", "sessiontoken",
}
SENSITIVE_SUFFIXES = ("password", "passwd", "secret", "token", "apikey", "privatekey",
                      "cookie", "cookies", "sessionid")
TEXT_CREDENTIAL = re.compile(
    r"^\s*[\"']?(password|passwd|secret|token|access_token|refresh_token|"
    r"authorization|api_key|private_key|client_secret|cookie|session_id)"
    r"[\"']?\s*[:=]", re.IGNORECASE | re.MULTILINE
)


class ReleaseError(ValueError):
    """The package is not ready to publish."""


def parse_version(value):
    if not isinstance(value, str):
        raise ReleaseError("version must be a string in YYYY.MM.DD.revision format")
    match = VERSION_PATTERN.fullmatch(value)
    if not match:
        raise ReleaseError("version must use YYYY.MM.DD.revision, with a nonnegative revision")
    parts = tuple(int(part) for part in match.groups())
    try:
        date(*parts[:3])
    except ValueError as error:
        raise ReleaseError("version contains an invalid calendar date") from error
    return parts


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReleaseError(f"cannot read JSON file: {path.name}") from error


def scan_text(text, label):
    # Report the file only; never echo potentially private matching values.
    if LOCAL_PATH.search(text):
        raise ReleaseError(f"local absolute path found in {label}")
    if ACCOUNT_URL.search(text):
        raise ReleaseError(f"account-specific Dianping URL found in {label}")
    if TEXT_CREDENTIAL.search(text):
        raise ReleaseError(f"credential-like field found in {label}")


def scan_json(value, label):
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
            if normalized in SENSITIVE_KEYS or normalized.endswith(SENSITIVE_SUFFIXES):
                raise ReleaseError(f"credential-like JSON key found in {label}")
            scan_text(key, label)
            scan_json(child, label)
    elif isinstance(value, list):
        for child in value:
            scan_json(child, label)
    elif isinstance(value, str):
        scan_text(value, label)


def distribution_files(root):
    """Inventory distributable files; private state and test fixtures are excluded."""
    files = []
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        base = Path(directory)
        kept = []
        for name in sorted(dirnames):
            if name in EXCLUDED_DIRS:
                continue
            if (base / name).is_symlink():
                raise ReleaseError("symlink directories are not supported in release packages")
            kept.append(name)
        dirnames[:] = kept
        for name in sorted(filenames):
            path = base / name
            relative = path.relative_to(root).as_posix()
            if relative in EXCLUDED_FILES or name.endswith((".pyc", ".pyo")):
                continue
            if path.is_symlink():
                raise ReleaseError(f"symlink file is not supported: {relative}")
            files.append((relative, path))
    return sorted(files)


def validate_restaurants(root):
    data = read_json(root / "data" / "favorites.json")
    if not isinstance(data, dict):
        raise ReleaseError("favorites.json must be an object")
    if type(data.get("schema_version")) is not int or data["schema_version"] < 1:
        raise ReleaseError("favorites.json needs a positive integer schema_version")
    rows = data.get("restaurants")
    metadata = data.get("metadata")
    if not isinstance(rows, list) or not isinstance(metadata, dict):
        raise ReleaseError("favorites.json needs restaurants array and metadata object")
    count = metadata.get("imported_restaurant_count")
    if type(count) is not int or count != len(rows):
        raise ReleaseError("metadata.imported_restaurant_count does not match restaurant count")
    expected = metadata.get("expected_restaurant_count")
    if expected is not None and (type(expected) is not int or expected < len(rows)):
        raise ReleaseError("metadata.expected_restaurant_count is invalid")
    ids = {"id": set(), "dianping_shop_id": set()}
    for number, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ReleaseError(f"restaurant {number} must be an object")
        for field, seen in ids.items():
            value = row.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ReleaseError(f"restaurant {number} has an invalid {field}")
            if value in seen:
                raise ReleaseError(f"duplicate restaurant {field}")
            seen.add(value)
        if not isinstance(row.get("name"), str) or not row["name"].strip():
            raise ReleaseError(f"restaurant {number} needs a name")
        if not isinstance(row.get("sources"), list):
            raise ReleaseError(f"restaurant {number} needs a sources array")
        if row.get("visited") is not None or row.get("liked") is not None:
            raise ReleaseError(f"personal visited/liked value in restaurant {number}")
        if row.get("user_feedback") not in (None, [], {}):
            raise ReleaseError(f"personal user_feedback in restaurant {number}")
    return data


def validate_and_hash(root):
    root = Path(root).resolve()
    for required in ("SKILL.md", "scripts/query_food.py", "data/favorites.json"):
        if not (root / required).is_file():
            raise ReleaseError(f"required package file missing: {required}")
    validate_restaurants(root)
    hashes = {}
    for relative, path in distribution_files(root):
        try:
            content = path.read_bytes()
            text = content.decode("utf-8-sig")
        except (OSError, UnicodeError) as error:
            raise ReleaseError(f"cannot inspect UTF-8 public file: {relative}") from error
        scan_text(text, relative)
        if path.suffix.lower() == ".json":
            try:
                value = json.loads(text)
            except json.JSONDecodeError as error:
                raise ReleaseError(f"invalid JSON in {relative}") from error
            scan_json(value, relative)
        # Git may normalize CRLF on checkout/commit. Hash canonical UTF-8 text
        # without BOM and with LF newlines so checks work on every platform.
        canonical = text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
        hashes[relative] = hashlib.sha256(canonical).hexdigest()
    return hashes


def check_release(root):
    root = Path(root).resolve()
    manifest = read_json(root / "version.json")
    if not isinstance(manifest, dict):
        raise ReleaseError("version.json must be an object")
    scan_json(manifest, "version.json")
    parse_version(manifest.get("version"))
    if manifest.get("repository") != REPOSITORY or manifest.get("branch") != BRANCH:
        raise ReleaseError("manifest repository or branch does not match this project")
    try:
        stamp = datetime.fromisoformat(manifest["released_at"])
        if stamp.utcoffset() is None:
            raise ValueError("timezone required")
    except (KeyError, TypeError, ValueError) as error:
        raise ReleaseError("manifest released_at must be an ISO date with timezone") from error
    actual = validate_and_hash(root)
    stored = manifest.get("sha256")
    if not isinstance(stored, dict) or stored != actual:
        raise ReleaseError("package files differ from manifest checksums; prepare a new release")
    return manifest


def prepare_release(root, version):
    root = Path(root).resolve()
    wanted = parse_version(version)
    manifest_path = root / "version.json"
    if manifest_path.exists():
        previous = read_json(manifest_path)
        if not isinstance(previous, dict):
            raise ReleaseError("existing version.json must be an object")
        if wanted <= parse_version(previous.get("version")):
            raise ReleaseError("new version must be strictly later than the existing version")
    hashes = validate_and_hash(root)
    manifest = {
        "version": version,
        "repository": REPOSITORY,
        "branch": BRANCH,
        "released_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "sha256": hashes,
    }
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         prefix=".release-", suffix=".tmp", dir=root,
                                         delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(manifest, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, manifest_path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--version", help="new version: YYYY.MM.DD.revision")
    action.add_argument("--check", action="store_true", help="verify the existing release manifest")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        manifest = check_release(root) if args.check else prepare_release(root, args.version)
    except (ReleaseError, OSError) as error:
        parser.exit(1, f"Release validation failed: {error}\n")
    action_name = "Verified" if args.check else "Prepared"
    print(f"{action_name} {manifest['version']}: {len(manifest['sha256'])} files")


if __name__ == "__main__":
    main()
