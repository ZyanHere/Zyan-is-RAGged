# Evaluation corpus — stage 3.1

**The documents in this directory are committed, not fetched.** That is a
deliberate reversal of the obvious design, and the reason is in the sources
below: two of the five publishers overwrite their file **in place** at the same
URL. The BLS release is replaced monthly; the IRS instructions change with the
tax year. A manifest of URLs plus a fetch script would mean the eval set
silently changed under us, and every "this improved recall by N" measured
against it would be comparing two different corpora.

So the bytes are the artifact and the hashes below are how you know they are
the same bytes. Module 3 of `docs/curriculum.md` asks for exactly this: *"The
eval set is a primary artifact of this project, not a side experiment. It is
version-controlled … Treat it with the same care as the source code."*

Four of the five rules in `.gitignore` that used to ignore this directory were
removed in the same change that created it.

## What is here

| File | Pages | Empty | Chars/page | MB | Page size |
|---|---:|---:|---:|---:|---|
| `acl-dpr-2020.pdf` | 13 | 0 | 4,317 | 0.39 | 595×841 |
| `apollo-11-mission-report.pdf` | 230 | 1 | 1,917 | 11.91 | 610×792 |
| `rfc9110-http-semantics.pdf` | 194 | 0 | 2,129 | 2.73 | 595×841 |
| `irs-1040-instructions.pdf` | 126 | 0 | 4,531 | 4.23 | 612×792 |
| **total** | **563** | | | **19.26** | |

`[measured]` 2026-10-28, `pypdf`, first 40 pages sampled per document — the
same method as `docs/experiments/0001`, so the two tables are comparable. Empty
pages and chars/page are *within the sample*, not across the whole document.

**Re-measured rather than copied.** Three of the four come back identical to
0001's September figures, which also tells us those three URLs have not
changed. Apollo 11 reads 1,917 chars/page against 0001's 1,966 — a different
`pypdf` version or a different sampling boundary, not a different file, since
nothing at `ntrs.nasa.gov` is rewritten. The difference is recorded rather than
quietly reconciled.

## Provenance

| File | Source | Licence | SHA-256 |
|---|---|---|---|
| `acl-dpr-2020.pdf` | `https://aclanthology.org/2020.emnlp-main.550.pdf` | CC BY 4.0 | `2abfc7991519be2b8ce30215905516fdb593218b7bf59e50ece0d8a088a7c4d5` |
| `apollo-11-mission-report.pdf` | `https://ntrs.nasa.gov/api/citations/19710015566/downloads/19710015566.pdf` | US Gov — public domain | `8b7192503c5b74dc1bc9686b6bd84560f6bbbf14fa851449ddd8ddaad6137d5d` |
| `rfc9110-http-semantics.pdf` | `https://www.rfc-editor.org/rfc/rfc9110.pdf` | IETF Trust / BCP 78 | `60b30efa1048900833d1758440247fe8ac85a3134f2327388dcb24e07d814c89` |
| `irs-1040-instructions.pdf` | `https://www.irs.gov/pub/irs-pdf/i1040gi.pdf` | US Gov — public domain | `482e9c487c608f1bbeaceef35bc3c0933e8b35443cfff447e4279d590468364a` |

Retrieved 2026-10-28. Verify with:

```powershell
Get-FileHash -Algorithm SHA256 benchmark\documents\*.pdf
```

**Mutable sources**, which is why the bytes are committed: `irs-1040-instructions.pdf`
is rewritten each tax year at the same path, and the BLS release below is
rewritten monthly. The IRS copy here is whatever that URL served on
2026-10-28 and its hash is the only durable identifier it has.

## Why each document is in the set

The corpus is chosen for the *layout failures* it contains. A corpus of clean
single-column prose would produce flattering numbers and hide exactly the
failures Module 4 exists to fix.

| File | The failure it tests |
|---|---|
| `acl-dpr-2020.pdf` | **two-column** academic layout, and running headers — 0001 already demonstrated the page number landing in the text as its own line |
| `apollo-11-mission-report.pdf` | **OCR damage**: a scanned document with a text layer that extracts badly. One empty page in the sample, and the lowest chars/page in the set |
| `rfc9110-http-semantics.pdf` | long single-column technical reference — dense cross-references and ABNF blocks, where a chunk boundary mid-grammar is the plausible failure |
| `irs-1040-instructions.pdf` | forms, worksheets and multi-column instructions |

## What is missing

**Three slots are open, and one of them blocks the 5–10 minimum.**

| Slot | Status |
|---|---|
| dense multi-level tables — **BLS CPI news release** | **fetch blocked.** `https://www.bls.gov/news.release/pdf/cpi.pdf` returns **403 Forbidden** to an automated request. Their edge rejects unrecognised agent strings, and working around that is bot-check circumvention, so it was not attempted. **A browser downloads it in one click** — save it here as `bls-cpi-news-release.pdf` and add its hash to the table above |
| a true image-only scan — zero extractable text | open. This is **16.2's trigger** (OCR), not a 3.1 requirement — Apollo 11 already covers *damaged* extraction. Deferred without cost |
| something you actually read | open, and a preference rather than a requirement. 0001's argument stands: *"anything you actually care about reading is the better one"* |

Stage 3.1 asks for 5–10 real documents. **Four are here**, so the BLS file —
or any substitute with dense multi-level tables — is what closes the minimum.

## What does not exist yet

The questions. 30–50 hand-written, each with a gold answer and the page or
pages that contain it. They are the long pole of stage 3.1 and they are not
engineering work.

**Write them reading the PDFs, not reading extracted text.** Questions written
from `pypdf` output are biased toward the extractor's successes: they
systematically avoid the pages where extraction already fails, which are
precisely the failures the instrument is being built to find. That is what the
curriculum's word *hand-written* is protecting.

Include deliberately unanswerable questions — stage 17.3 calibrates abstention
against them, and a retrieval metric that has never seen a question with no
answer cannot tell you what the system does when there is nothing to find.
