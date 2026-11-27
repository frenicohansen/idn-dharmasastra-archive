"""BPK PDF -> archive.org -> mapping file.

For each regulation of one jenis on peraturan.bpk.go.id: download its PDFs, upload each to the
archive.org item of its jenis and year, and write one mapping file per PDF:

    data/mapping/<jenis>/<id>.yaml

Ids: <jenis>_<nomor>_<tahun> for the first PDF
of a regulation (uu_4_2009), <id>_2, <id>_3 for further PDFs. The id is also the file name on
archive.org: https://archive.org/download/peraturan-indonesia-<jenis>-<tahun>/<id>.pdf

Regulations with a mapping file are skipped, so runs resume. Needs a virtual display (xvfb).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import internetarchive
import yaml
from hukum_bersih.sources import peraturan_bpk as bpk
from hukum_bersih.sources.bpk_session import BASE, Session

MAPPING = Path("data/mapping")
TYPE_TITLE = bpk.JENIS_TITLE


def item_for(jenis: str, year: str) -> str:
    return f"peraturan-indonesia-{jenis}-{year}"


def mapped(jenis: str) -> tuple[set[str], set[str]]:
    """(ids, BPK detail URLs) already in the mapping."""
    ids, urls = set(), set()
    for p in (MAPPING / jenis).glob("*.yaml"):
        ids.add(p.stem)
        urls.add(yaml.safe_load(p.read_text())["bpk_detail_url"])
    return ids, urls


def upload(jenis: str, year: str, key: str, pdf: Path) -> str:
    item = item_for(jenis, year)
    metadata = {
        "title": f"Peraturan Indonesia: {TYPE_TITLE[jenis]} Tahun {year}",
        "creator": "Pemerintah Republik Indonesia",
        "mediatype": "texts",
        "collection": "opensource",
        "language": "ind",
        "coverage": "Indonesia",
        "subject": ["peraturan perundang-undangan", "hukum indonesia", TYPE_TITLE[jenis].lower(),
                    jenis, f"tahun {year}"],
    }
    responses = internetarchive.upload(
        item, files={key: str(pdf)}, metadata=metadata, retries=5, retries_sleep=30,
        access_key=os.environ["IA_ACCESS_KEY"], secret_key=os.environ["IA_SECRET_KEY"])
    if not all(r.status_code == 200 for r in responses):
        raise RuntimeError(f"{item}/{key}: upload rejected ({[r.status_code for r in responses]})")
    return item


def process(session, listing, jenis: str, only: set[str], done_ids: set[str]) -> list[str]:
    detail_url = BASE + listing.path
    d = bpk.parse_detail(session.get(listing.path).text)
    if not d["meta"].get("Nomor"):
        return [f"skip {listing.path}: no metadata"]
    work = bpk.work_id(d["meta"], jenis)
    if only and work not in only:
        return []
    if not d["files"]:
        return [f"skip {work}: no PDF on BPK"]
    year = d["meta"]["Tahun"]
    entries = []
    with tempfile.TemporaryDirectory() as tmp:
        for n, f in enumerate(d["files"], start=1):
            file_id = work if n == 1 else f"{work}_{n}"
            if file_id in done_ids:
                continue
            content = session.get(f["url"]).content
            if not content.startswith(b"%PDF"):
                raise RuntimeError(f"{f['url']}: not a PDF")
            pdf = Path(tmp) / f"{file_id}.pdf"
            pdf.write_bytes(content)
            item = upload(jenis, year, f"{file_id}.pdf", pdf)
            entries.append((file_id, {
                "id": file_id,
                "bpk_detail_url": detail_url,
                "bpk_url": f["url"],
                "bpk_filename": f["filename"],
                "archive_item": item,
                "archive_url": f"https://archive.org/download/{item}/{file_id}.pdf",
                "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content),
                "uploaded_at": datetime.now(UTC).isoformat(timespec="seconds"),
            }))
    # written only once every PDF of the regulation is up, so a crash re-does the whole regulation
    (MAPPING / jenis).mkdir(parents=True, exist_ok=True)
    for file_id, entry in entries:
        (MAPPING / jenis / f"{file_id}.yaml").write_text(
            yaml.safe_dump(entry, sort_keys=False, allow_unicode=True))
    return [f"ok   {e[0]} -> {e[1]['archive_url']}" for e in entries]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("jenis", choices=sorted(bpk.JENIS_ID))
    ap.add_argument("--limit", type=int, default=0, help="stop after N regulations uploaded (0 = all)")
    ap.add_argument("--only", default="", help="comma-separated ids (uu_4_2009,...): just these")
    ap.add_argument("--budget-minutes", type=float, default=0,
                    help="stop starting new regulations after this long (0 = no limit); "
                         "sets output left=yes in $GITHUB_OUTPUT so the workflow can chain")
    ap.add_argument("--delay", type=float, default=3.0, help="seconds between BPK requests")
    args = ap.parse_args()

    only = {i for i in args.only.split(",") if i}
    done_ids, done_urls = mapped(args.jenis)
    session = Session(delay=args.delay, state=Path(os.environ.get("HUKUM_BERSIH_BPK_STATE", "bpk-state.json")))
    uploaded, left = 0, False
    deadline = time.monotonic() + args.budget_minutes * 60
    for listing in bpk.listings(session, args.jenis):
        if BASE + listing.path in done_urls:
            continue
        if args.budget_minutes and time.monotonic() >= deadline:
            left = True
            break
        try:
            lines = process(session, listing, args.jenis, only, done_ids)
        except Exception as e:
            if type(e).__name__ == "Challenged":
                print(f"STOP Cloudflare: {e}")
                return 1
            print(f"FAIL {listing.path}: {type(e).__name__}: {e}")
            continue
        print("\n".join(lines), flush=True)
        uploaded += sum(l.startswith("ok") for l in lines) > 0
        if args.limit and uploaded >= args.limit:
            break
    print(f"done {uploaded} regulation(s)" + ("; out of time, work left" if left else ""))
    if out := os.environ.get("GITHUB_OUTPUT"):
        with open(out, "a") as f:
            f.write(f"uploaded={uploaded}\nleft={'yes' if left else 'no'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
