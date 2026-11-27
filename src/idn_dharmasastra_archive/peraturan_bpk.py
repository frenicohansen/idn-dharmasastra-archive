"""peraturan.bpk.go.id (Database Peraturan JDIH BPK): the listing and detail page parsers, and
the id of each regulation."""

from __future__ import annotations

import html
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

from .bpk_session import BASE

SOURCE = "peraturan.bpk.go.id"
JENIS_ID = {"uu": 8, "perppu": 9, "pp": 10, "perpres": 11}    # BPK's "jenis" filter values
BENTUK = {"uu": "uu", "perpu": "perppu", "perppu": "perppu", "pp": "pp", "perpres": "perpres"}
JENIS_TITLE = {"uu": "Undang-Undang", "perppu": "Peraturan Pemerintah Pengganti Undang-Undang",
               "pp": "Peraturan Pemerintah", "perpres": "Peraturan Presiden"}


# ---- parsing---------------------------------------------------------------------------

def clean(fragment: str) -> str:
    """HTML fragment -> plain text on one line."""
    text = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True)
class Listing:
    path: str      # /Details/38578/uu-no-4-tahun-2009
    bpk_id: int


def parse_listing(text: str) -> list[Listing]:
    # each result's heading link ("Undang-undang (UU) Nomor 5 Tahun 2026"); the status lines
    # under a result link to related regulations, which are not results themselves
    paths = dict.fromkeys(re.findall(
        r'<a class="text-gray-600 text-decoration-none" href="(/Details/\d+/[^"#?]+)"', text))
    return [Listing(p, int(p.split("/")[2])) for p in paths]


def last_page(text: str) -> int:
    pages = [int(p) for p in re.findall(r"[?&](?:amp;)?p=(\d+)", text)]
    return max(pages, default=1)


def cite_to_id(citation: str) -> str | None:
    """'UU No. 2 Tahun 2025' -> 'uu_2_2025'; 'PERPU No. 2 Tahun 2022' -> 'perppu_2_2022'."""
    m = re.match(r"\s*(UU|PERPU|PERPPU|PP|PERPRES)\s+No\.?\s*([0-9]+[A-Za-z]?)\s+Tahun\s+(\d{4})\s*$",
                 citation, re.IGNORECASE)
    return f"{BENTUK[m[1].lower()]}_{m[2].lower()}_{m[3]}" if m else None


def _attrs(tag: str) -> dict[str, str]:
    return {k: html.unescape(v) for k, v in re.findall(r'([\w-]+)="([^"]*)"', tag)}


def parse_detail(text: str) -> dict:
    """Detail page -> {'meta': {label: value}, 'files', 'uji_materi', 'status_peraturan'}."""
    meta = {}
    for label, value in re.findall(
        r'<div class="col-lg-3 fw-bold">(.*?)</div>\s*<div class="col-lg-9">(.*?)</div>', text, re.DOTALL
    ):
        meta[clean(label)] = clean(value)

    files = []
    for tag in re.findall(r"<a\b[^>]*>", text):
        a = _attrs(tag)
        if a.get("data-kategori") == "Peraturan" and a.get("href", "").startswith("/Download/"):
            files.append({"url": BASE + a["href"], "bpk_file_id": int(a["data-id"]),
                          "filename": unquote(a["href"].rsplit("/", 1)[-1])})

    uji_materi = []
    for tag, putusan, rest in re.findall(
        r'(<a\b[^>]*data-kategori="UjiMateri"[^>]*>)(.*?)</a>(.*?)(?=data-kategori="UjiMateri"|UJI MATERI|$)',
        text, re.DOTALL,
    ):
        amar = re.search(r"<span>(.*?)</span>", rest, re.DOTALL)
        uji_materi.append({"putusan": clean(putusan), "url": BASE + _attrs(tag)["href"],
                           "amar": clean(amar[1]) if amar else None})

    status: dict[str, list[dict]] = {}
    block = text[text.find("STATUS <span"):]
    block = block[: block.find("ABSTRAK <span")] if "ABSTRAK <span" in block else block
    for heading, items in re.findall(
        r'<div class="col-12 fw-semibold bg-light-primary p-4">\s*(.*?)\s*</div>.*?<ol[^>]*>(.*?)</ol>',
        block, re.DOTALL,
    ):
        entries = []
        for li in re.findall(r"<li[^>]*>(.*?)</li>", items, re.DOTALL):
            link = re.search(r'<a[^>]*href="(/Details/[^"]+)"[^>]*>(.*?)</a>', li, re.DOTALL)
            note = re.search(r"<br\s*/?>\s*<span>(.*?)</span>", li, re.DOTALL)
            body = re.sub(r"<br\s*/?>\s*<span>.*?</span>", "", li, flags=re.DOTALL)
            if link:
                citation = clean(link[2])
                tentang = clean(body.split("</a>", 1)[1]).removeprefix("tentang").strip()
                entries.append({"id": cite_to_id(citation), "citation": citation,
                                "tentang": tentang or None, "url": BASE + link[1],
                                "note": (clean(note[1]) or None) if note else None})
            else:
                entries.append({"id": None, "citation": clean(body), "tentang": None,
                                "url": None, "note": (clean(note[1]) or None) if note else None})
        status[clean(heading).rstrip(" :")] = entries
    return {"meta": meta, "files": files, "uji_materi": uji_materi, "status_peraturan": status}


def work_id(meta: dict, jenis: str) -> str:
    from .naming import validate_id

    bentuk = BENTUK.get(meta.get("Bentuk Singkat", "").lower(), jenis)
    nomor = re.sub(r"\s+", "", meta.get("Nomor", "")).lower()
    return validate_id(f"{bentuk}_{nomor}_{meta.get('Tahun', '')}")


# ---- records -------------------------------------------------------------------------------


def listings(session, jenis: str, cache: Path | None = None) -> Iterator[Listing]:
    """Every regulation of ``jenis`` in BPK's listing, newest first. ``cache``: a folder that
    keeps the listing pages, so later batches of one workflow run read them from disk instead
    of walking ~190 pages again (~9.5 min a batch); a new run starts with an empty folder."""
    page, last = 1, 1
    while page <= last:
        saved = cache / f"{jenis}_{page}.html" if cache else None
        if saved and saved.exists():
            text = saved.read_text()
        else:
            text = session.get(f"/Search?jenis={JENIS_ID[jenis]}&p={page}").text
            if saved:
                saved.write_text(text)
        last = max(last, last_page(text))
        items = parse_listing(text)
        if not items:
            return
        yield from items
        page += 1
