"""Check the mapping against archive.org and stamp what is really there.

For every mapping file without `verified_at` (data/mapping/<jenis>/<id>.yaml), look the file up in
its item's metadata (https://archive.org/metadata/<item>, one request per item) and compare the
size with `bytes`. Passing files get `verified_at`; missing files and size mismatches are
printed and left unstamped, so a later run checks them again.

With --delete-missing, the mapping files of a regulation that has a missing or mismatched PDF are
deleted instead, all of them (archive-bpk skips a regulation while any of its mappings exists), so
the next archive-bpk run uploads it again.

Usage: verify-mapping [jenis] [--delete-missing]    (without jenis: all of data/mapping)
Exit status 1 when something is not (yet) on archive.org as uploaded and was not deleted.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import yaml

MAPPING = Path("data/mapping")


def item_files(item: str) -> dict[str, int]:
    """file name -> size in the item; empty when the item does not exist (yet)."""
    with urllib.request.urlopen(f"https://archive.org/metadata/{item}", timeout=60) as r:
        meta = json.load(r)
    return {f["name"]: int(f["size"]) for f in meta.get("files", []) if "size" in f}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("jenis", nargs="?", default="")
    ap.add_argument("--delete-missing", action="store_true",
                    help="delete the mappings of regulations with a missing or mismatched PDF")
    args = ap.parse_args()

    folders = [MAPPING / args.jenis] if args.jenis else sorted(MAPPING.glob("*"))
    todo: dict[str, list[tuple[Path, dict]]] = defaultdict(list)
    for folder in folders:
        for path in sorted(folder.glob("*.yaml")):
            entry = yaml.safe_load(path.read_text())
            if "verified_at" not in entry:
                todo[entry["archive_item"]].append((path, entry))

    verified = problems = 0
    bad_regulations: set[str] = set()
    for item, entries in sorted(todo.items()):
        files = item_files(item)
        for path, entry in entries:
            name = f"{entry['id']}.pdf"
            if name not in files:
                print(f"MISSING {entry['id']}: not in {item} (yet)")
            elif files[name] != entry["bytes"]:
                print(f"SIZE    {entry['id']}: archive.org has {files[name]} bytes, uploaded {entry['bytes']}")
            else:
                entry["verified_at"] = datetime.now(UTC).isoformat(timespec="seconds")
                path.write_text(yaml.safe_dump(entry, sort_keys=False, allow_unicode=True))
                verified += 1
                continue
            problems += 1
            bad_regulations.add(entry["bpk_detail_url"])

    deleted = 0
    if args.delete_missing and bad_regulations:
        for path in sorted(MAPPING.glob("*/*.yaml")):
            if yaml.safe_load(path.read_text())["bpk_detail_url"] in bad_regulations:
                print(f"DELETED {path.stem}: will be uploaded again by archive-bpk")
                path.unlink()
                deleted += 1
        problems = 0

    print(f"done {verified} verified, {problems} not on archive.org as uploaded, {deleted} mapping file(s) deleted")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
