# idn-dharmasastra-archive

Archive of Indonesian regulation PDFs from [peraturan.bpk.go.id](https://peraturan.bpk.go.id)
(JDIH BPK) on [archive.org](https://archive.org), with a mapping from each archive.org copy back
to its BPK original.

## How it works

The workflow `.github/workflows/archive-bpk.yml` (manual run) does, for one type of regulation
(`uu`, `perppu`, `pp`, `perpres`):

1. Walks BPK's listing and downloads each regulation's PDFs. BPK sits behind Cloudflare, so the
   scraping code of [dhantyo/hukum-bersih](https://github.com/dhantyo/hukum-bersih) is checked
   out and reused.
2. Uploads each PDF to archive.org.
3. Commits one mapping file per PDF to this repo.

Regulations that already have a mapping are skipped, so runs resume. A run stops starting new
regulations after 5 h 25 min (GitHub stops jobs at 6 h), commits, and starts the next run by
itself while work is left. Runs started with `only` or by failing do not chain.

## Ids and layout

Ids follow hukum-bersih's naming rule: `<jenis>_<nomor>_<tahun>`, e.g. `uu_4_2009`. A
regulation with several PDFs gets `uu_4_2009_2`, `uu_4_2009_3`, …

| What | Where |
|---|---|
| archive.org item (one per type and year) | `peraturan-indonesia-<jenis>-<tahun>` |
| file in the item | `<id>.pdf` |
| download URL | `https://archive.org/download/peraturan-indonesia-<jenis>-<tahun>/<id>.pdf` |
| mapping | `data/mapping/<jenis>/<id>.yaml` |

A mapping file:

```yaml
id: uu_4_2009
bpk_detail_url: https://peraturan.bpk.go.id/Details/38578/uu-no-4-tahun-2009
bpk_url: https://peraturan.bpk.go.id/Download/...
bpk_filename: ...
archive_item: peraturan-indonesia-uu-2009
archive_url: https://archive.org/download/peraturan-indonesia-uu-2009/uu_4_2009.pdf
sha256: ...
bytes: 123456
uploaded_at: '2026-11-27T10:00:00+00:00'
```

## Setup

Add two repository secrets, from <https://archive.org/account/s3.php>:
`IA_ACCESS_KEY` and `IA_SECRET_KEY`.

## Running

Actions → *Archive BPK PDFs* → Run workflow.

| Input | Meaning |
|---|---|
| `jenis` | type of regulation |
| `limit` | max regulations to upload (0 = all; runs chain by themselves) |
| `only` | just these ids, comma-separated (e.g. `uu_4_2009,uu_31_1999`); never chains |

Try `only=uu_4_2009`, `limit=1` first.

The script can also run locally (needs `../hukum-bersih`, a virtual display, and the two keys
in the environment):

```sh
xvfb-run -a uv run --project ../hukum-bersih/pipeline --extra bpk --with internetarchive \
  python scripts/archive_bpk.py uu --only uu_4_2009
```

## License

See [LICENSE](LICENSE).
