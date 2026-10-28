# The question set — stage 3.1

**This is the long pole of stage 3.1, and it is reading work rather than
engineering work.** 30–50 questions over the documents in
`../documents/`, each with a gold answer and the page or pages that contain
it. Everything else in Module 3 — the runner, the metrics, the failure
attribution in 3.2, the regression gate in 3.3 — is machinery that measures
against this file. Nothing downstream can be better than it is.

Write them into `questions.csv`. `questions.example.csv` holds the header and
five worked examples.

**Every fact and page number in those five was verified against the PDF on
disk**, which is also why there is no `table` or `multi_page` example: the
dense-tables document is the one that is still missing, and I was not going to
invent a page number to demonstrate a format. Those two types are yours to
write first, because they are the ones most likely to expose something.

---

## The one discipline that matters most

**Write the questions reading the PDFs, not reading extracted text.**

Questions written against `pypdf` output are biased toward the extractor's
successes. You would be reading the text the retriever already sees, so you
would unconsciously avoid the pages where extraction is mangled — and those
pages are precisely the failures this instrument is being built to find. A
corpus chosen for its layout problems, measured by a question set that routes
around them, is the synthetic-fixture mistake rebuilt out of real documents.

Open the PDF in a viewer. Read it as a person. Ask what you would actually
want to know.

## What the extraction already looks like

Not to write questions from — to show you the damage is real and already
present on page 1 of the cleanest document in the set.

```text
acl-dpr-2020.pdf, page 1
    6769                                  <- the page number, its own line
    Open-domain question answering relies on ef-
    ﬁcient passage retrieval ...          <- hyphen split + "fi" ligature
    Vladimir Karpukhin∗, Barlas O˘guz∗    <- mangled diacritic
```

```text
rfc9110-http-semantics.pdf, page 138
    ... respond with a status code of 404 (not found). should not may may
                                          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                          RFC 2119 keywords, rendered as
                                          sidebar glyphs, land in the text
                                          as a run of loose words
```

Ligatures (`conﬂict`, `deﬁnitions`, `eﬀect`) are everywhere in RFC 9110.

## The schema

`questions.csv`, authored in a spreadsheet and saved as CSV:

| Column | What it holds |
|---|---|
| `id` | stable identifier, e.g. `rfc-004`. **Never renumber.** Results are compared across runs by id, and a renumbered question is a different question with a familiar name |
| `document` | a filename in `../documents/`, exactly. Set it for a `near_miss` too — it names the document the question is *near*, which is what makes the miss hard. **Empty only for `out_of_domain`**, where no document is relevant by definition |
| `question` | what you would actually ask |
| `gold_pages` | 1-indexed page numbers, `138` or `73;74`. Semicolon-separated, because the comma is the delimiter. **Empty when unanswerable** |
| `gold_answer` | the fact, in your own words. Not a quote — the runner never grades text, see below |
| `type` | one of the seven below. This is what the metrics are sliced by |
| `answerable` | `true` or `false` |

### `type`, and why slicing matters

Stage 3.1 asks for *"metrics, sliced by question type"*, and the reason is that
one aggregate number hides the thing you need. 62% recall could be "uniformly
mediocre" or "excellent on single facts, hopeless on tables" — and only the
second tells you what to fix.

| `type` | Meaning |
|---|---|
| `lookup` | one fact, stated plainly, on one page |
| `numeric` | a number, date or quantity — the answer is wrong if a digit is wrong |
| `definition` | what a term means, where the document defines it |
| `table` | the answer lives in a table. Expect these to be the worst, and that is the point |
| `multi_page` | genuinely needs evidence from more than one page. Keep a handful: they are what `recall@k` with k>1 is for |
| `near_miss` | **unanswerable**, and the topic *is* in the corpus. The hardest and most valuable kind |
| `out_of_domain` | **unanswerable**, and nothing related is in the corpus. Easy, and worth a few as a floor |

### Include unanswerable questions

Roughly a fifth of the set. Stage 17.3 calibrates abstention against them, and
a retrieval metric that has never seen a question with no answer cannot tell
you what the system does when there is nothing to find — which is the single
most common real failure of a RAG system.

**`near_miss` is where the value is.** Example 4 below asks what status code
HTTP defines for rate limiting. RFC 9110 is 194 pages of status-code
definitions and it does not contain `429` or the phrase "Too Many Requests"
anywhere — that is RFC 6585. So retrieval will confidently return *a* status
code page, and the correct behaviour is to find nothing worth returning. An
`out_of_domain` question gets that right by accident; a `near_miss` has to earn
it.

## What `gold_answer` is for, and what it is not

**The runner will not grade answer text.** Stage 3.1 measures *retrieval*: did
the chunks that came back include the page where the answer is? That is a
comparison of page numbers, and it needs no language model — which is exactly
why 3.1 comes before 3.3, where an LLM judge first appears.

So `gold_answer` is there for three other reasons:

1. it forces you to confirm the answer really is on that page before you write
   the row down,
2. 3.3's judge needs it, and writing it twice is worse than writing it once,
3. when a question fails, it is what tells you whether the question was fair.

Write it as a short fact, not a quote. A quote invites someone to build string
matching on it later, and string matching against ligature-damaged extraction
is a measurement of `pypdf`, not of retrieval.

## Picking `gold_pages` — the mistake to avoid

**The gold page is the page with the *answer*, not every page that mentions the
term.** This is the most common way a hand-written eval set goes quietly wrong,
and the corpus already demonstrates it:

```text
"404 Not Found" appears in rfc9110 on pages 9, 138, 162, 183
      page 9    the table of contents
      page 138  the definition          <- the only gold page
      page 162  cross-reference
      page 183  the index
```

If you list all four, a retriever that returns the table of contents scores a
hit, and your instrument now rewards the single most useless result it could
possibly produce. Same trap with `idempotent`: page 6 is the contents, page 73
is the definition.

Use `multi_page` only when the answer genuinely requires both pages, not when
the topic appears on both.

## When you are done

30 is enough to start; 50 is better. Spread them across all the documents, and
deliberately include questions you expect to **fail** — a set the system passes
completely measures nothing.

Then say so, and the runner gets built around this file.

## On the file format

CSV, because a spreadsheet is the pleasant way to write fifty rows by hand and
`csv` is in the standard library. The cost is real: a stray newline inside a
cell, or a semicolon where a comma belongs, is a silent malformation.

So the runner's loader will **validate every row and report every bad one** —
unknown document, page number out of range, `answerable=true` with no
`gold_pages`, a duplicate `id` — rather than failing on the first and leaving
you to find the rest one at a time. A malformed question set must not be able
to produce a baseline, which is the same all-or-nothing rule `retrieve_many`
already applies to its inputs.

JSONL was the alternative, and it is better at exactly one thing: a broken line
fails in isolation. It is worse at the thing that actually matters here, which
is being tolerable to hand-write fifty times.
