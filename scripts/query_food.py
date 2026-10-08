#!/usr/bin/env python3
"""Read local favorites and retrieve candidates; this does not judge suitability."""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

from check_update import check_update


SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATA = SKILL_DIR / "data" / "favorites.json"
DEFAULT_FEEDBACK = SKILL_DIR / "user-data" / "feedback.json"
KEYWORD_FIELDS = ("name", "cuisines", "taste_tags", "notes")


def apply_feedback(restaurants, path):
    """Overlay only personal fields, never rewrite the shared snapshot."""
    if path is None or not path.exists():
        return restaurants
    feedback = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(feedback, dict) or not isinstance(feedback.get("restaurants"), dict):
        raise ValueError("feedback must contain a restaurants object keyed by local restaurant id")
    for key, entry in feedback["restaurants"].items():
        if not isinstance(entry, dict):
            raise ValueError(f"feedback for {key} must be an object")
        if any(entry.get(field) is not None and type(entry[field]) is not bool
               for field in ("visited", "liked")):
            raise ValueError(f"visited/liked for {key} must be true, false, or null")
        if "user_feedback" in entry and not isinstance(entry["user_feedback"], list):
            raise ValueError(f"user_feedback for {key} must be an array")
    result = []
    for row in restaurants:
        entry = feedback["restaurants"].get(row.get("id"), {})
        merged = dict(row)
        merged.update({key: entry[key] for key in ("visited", "liked", "user_feedback") if key in entry})
        result.append(merged)
    return result


def normalized_city(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    if value.endswith("市"):
        value = value[:-1]
    return value or None


def text_values(value):
    """Accept empty fields and string/list/object notes without inventing text."""
    if isinstance(value, str):
        yield value.casefold()
    elif isinstance(value, list):
        for item in value:
            yield from text_values(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from text_values(item)


def nonnegative(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--summary", action="store_true",
                        help="return metadata and city counts for matching records")
    parser.add_argument("--city", help="exact city, with an optional trailing 市")
    parser.add_argument("--keyword", action="append", default=[],
                        help="repeatable OR search in name, cuisines, taste_tags, notes")
    parser.add_argument("--limit", type=nonnegative, default=20)
    parser.add_argument("--offset", type=nonnegative, default=0)
    parser.add_argument("--feedback", type=Path,
                        help="personal feedback overlay; default only applies to the bundled data")
    parser.add_argument("--no-update-check", action="store_true",
                        help="query fully offline without checking GitHub")
    args = parser.parse_args()

    city = normalized_city(args.city)
    if args.city is not None and city is None:
        parser.error("--city must contain a city name")
    keywords = [word.strip().casefold() for word in args.keyword]
    if any(not word for word in keywords):
        parser.error("--keyword must not be empty")

    try:
        data = json.loads(args.data.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        parser.error(f"cannot read data: {error}")
    if not isinstance(data, dict) or not isinstance(data.get("restaurants"), list):
        parser.error("data must be an object containing a restaurants array")
    restaurants = data["restaurants"]
    if any(not isinstance(row, dict) for row in restaurants):
        parser.error("every restaurant must be an object")
    feedback_path = args.feedback
    if feedback_path is None and args.data.resolve() == DEFAULT_DATA.resolve():
        feedback_path = DEFAULT_FEEDBACK
    try:
        restaurants = apply_feedback(restaurants, feedback_path)
    except (OSError, UnicodeError, ValueError) as error:
        parser.error(f"cannot read personal feedback: {error}")

    matches = []
    for row in restaurants:
        if city is not None and normalized_city(row.get("city")) != city:
            continue
        if keywords:
            texts = [text for field in KEYWORD_FIELDS
                     for text in text_values(row.get(field))]
            if not any(word in text for word in keywords for text in texts):
                continue
        matches.append(row)

    result = {
        "query": {"city": city, "keywords": keywords, "keyword_mode": "OR",
                  "keyword_fields": list(KEYWORD_FIELDS)},
        "total_records": len(restaurants),
        "total_matches": len(matches),
    }
    result["update"] = ({"status": "skipped", "message": "已按参数跳过联网检查，版本是否最新未知。"}
                        if args.no_update_check else check_update(SKILL_DIR))
    if args.summary:
        counts = Counter(normalized_city(row.get("city")) for row in matches)
        result["metadata"] = data.get("metadata", {})
        result["city_counts"] = [
            {"city": name, "count": count}
            for name, count in sorted(counts.items(),
                                      key=lambda item: (-item[1], item[0] or ""))
        ]
    else:
        rows = matches[args.offset:args.offset + args.limit]
        result.update({"offset": args.offset, "limit": args.limit,
                       "returned_count": len(rows), "restaurants": rows})

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
