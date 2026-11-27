"""Ids, following docs/NAMING.md."""

from __future__ import annotations

import re

PART = r"[a-z0-9]+(?:-[a-z0-9]+)*"
ID_RE = re.compile(rf"^{PART}(?:_{PART})*$")
DATE = r"\d{4}(?:-\d{2}){0,2}"
# <jenis>_<nomor>_<tahun>[_<date>[_<n>]]  (<n>: 2, 3 … for a version's further files)
REGULATION_RE = re.compile(
    rf"^(?P<work>(?P<jenis>[a-z]+(?:-[a-z]+)*)_(?P<nomor>\d+[a-z]?)_(?P<tahun>\d{{4}}))"
    rf"(?:_(?P<date>{DATE})(?:_(?P<n>\d+))?)?$"
)
# ruu_<slug>_<date>_<type>[_<who>][_<n>]
RUU_DOC_RE = re.compile(
    rf"^ruu_(?P<slug>{PART})_(?P<date>{DATE})_(?P<type>{PART})"
    rf"(?:_(?P<who>[a-z]+(?:-[a-z]+)*))?(?:_(?P<n>\d+))?$"
)
ID_MAX = 100   # longest id, in characters

RUU_TYPES = frozenset({
    "draft",
    "draft-final",
    "naskah-akademik",
    "naskah-urgensi",
    "dim",
    "surat-presiden",
    "laporan-komisi",
    "tanggapan-pemerintah",
    "pandangan-mini-fraksi",
    "risalah-rapat",
    "laporan-singkat",
    "bahan-narasumber",
    "dokumen-pendukung",
})


def validate_id(doc_id: str) -> str:
    if not ID_RE.match(doc_id) or len(doc_id) > ID_MAX:
        raise ValueError(
            f"invalid id {doc_id!r}: lowercase parts joined by '_', words inside a part by '-', "
            f"at most {ID_MAX} characters (see docs/NAMING.md)"
        )
    if doc_id.startswith("ruu_"):
        m = RUU_DOC_RE.match(doc_id)
        if not m or m["type"] not in RUU_TYPES:
            raise ValueError(
                f"invalid RUU document id {doc_id!r}: expected "
                f"ruu_<slug>_<date>_<type>[_<who>][_<n>] with type in {sorted(RUU_TYPES)}"
            )
    elif not REGULATION_RE.match(doc_id):
        raise ValueError(
            f"invalid regulation id {doc_id!r}: expected <jenis>_<nomor>_<tahun>[_<YYYY-MM-DD>[_<n>]], "
            "e.g. uu_11_2008 or uu_11_2008_2008-04-21"
        )
    return doc_id
