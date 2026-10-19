"""Print the s0036_doc collections with counts and sample documents (mongosh is not installed).

Usage: .venv/bin/python scripts/hw6_show_collections.py [USER_ID] [--collection NAME] [--limit N]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from pprint import pformat

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.hw6_mongo_database import get_mongo_database  # noqa: E402


def shorten(document: dict) -> dict:
    result = dict(document)
    if isinstance(result.get("embedding"), list):
        values = result["embedding"]
        result["embedding"] = [round(v, 4) for v in values[:4]] + [f"... {len(values)} floats total"]
    for key in ("text", "content"):
        if isinstance(result.get(key), str) and len(result[key]) > 220:
            result[key] = result[key][:220] + " ..."
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("user_id", nargs="?")
    parser.add_argument("--collection", action="append")
    parser.add_argument("--limit", type=int, default=1)
    args = parser.parse_args()
    db = get_mongo_database()
    print(f"database: {db.name}")
    for name in sorted(db.list_collection_names()):
        print(f"  {name}: {db[name].count_documents({})} documents")
    for name in args.collection or []:
        query = {"user_id": args.user_id} if args.user_id and name != "vulnerability_documents" else {}
        print(f"\n{db.name}> db.{name}.find({query or ''}).sort({{created_at: -1}}).limit({args.limit})"
              f"   // {db[name].count_documents(query)} matching")
        for document in db[name].find(query).sort("created_at", -1).limit(args.limit):
            print(pformat(shorten(document), sort_dicts=False, width=130))


if __name__ == "__main__":
    main()
