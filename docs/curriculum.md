# myRAG — Evolution Map

**What this is:** the complete destination, laid out as a causal chain. Each stage
is entered only when the previous system actually produces the problem it solves.

**How to read it:** the `Next problem` of every stage is the `Trigger` of the next
one. If you ever reach a stage whose trigger you cannot observe in your own
running system, **you are not ready for that stage** — skip it and come back.

**Stage sizes are deliberately uneven.** Some are an afternoon. Some are a month.
A stage is done when its metric moved and you can explain the tradeoff, not when
a number of days has passed.

---

## Ratings

| Mark | Meaning |
|---|---|
| **CORE** | Interview mastery. Gets asked. Do these. |
| **ADV** | Advanced. Strong differentiator, not a prerequisite for employment. |
| **OPT** | Optional. Do when curious or when the system genuinely demands it. |

### The interview-readiness checkpoint

**After Module 10 you should have enough backend and systems knowledge to hold
serious backend interviews.** That is not the same as "employable" — hiring also
turns on DSA, communication, prior experience, role fit and competition, none of
which this project supplies.

What Module 10 buys you is that the *systems* half of the interview stops being a
weakness.

**Apply throughout.** Modules 11–19 are not a prerequisite to applying; they are
what you keep doing while applying. Waiting until Module 19 to start interviewing
would be a serious mistake.

---

## Cross-cutting: things that arrive when needed, not as a module

- **Docker** arrives at stage 1.2, because Postgres needs it. Not a deployment
  milestone — a local dev necessity.
- **The fake embedder** arrives at stage 2.4. A local function returning a
  deterministic vector after a configurable sleep. Without it you cannot load
  test anything: a hosted embedding API's free tier dies in minutes, and a paid
  one costs thousands. It also lets you *simulate* provider slowness precisely.
- **Structured logging + correlation IDs** arrive at stage 2.4, not at the
  observability module. You cannot debug a background worker you cannot see.
- **Testing is a thread, not a module.** From stage 1.1 onward, every layer grows
  its own kind of test:

  | Kind | Answers | Arrives |
  |---|---|---|
  | unit | does this function behave? | 1.1 |
  | integration | do the pieces agree across a real DB/queue? | 1.2 |
  | concurrency | does it still hold with N actors? | 2.1 |
  | failure injection | what happens when a dependency dies? | 2.1 |
  | RAG evaluation | did answer quality change? | 3.1 |
  | load | what breaks first, and at what rate? | 11.1 |
  | regression | has a fixed bug come back? | continuous |

  **The rule that matters most: every failure you fix gets a regression test
  named after it.** Do that consistently and the test suite becomes a written
  history of every way this system has broken — which is both the best defence
  against regressions and the best interview material the project produces.

---

## The constitutional rule

> **Never add a technology because you reached its chapter. Add it only because
> the running system produced a problem that technology solves.**

```text
Need a cache?          prove repeated expensive work, with numbers.
Need Redis?            prove the current mechanism cannot meet the requirement.
Need more workers?     prove one cannot meet the throughput/SLO.
Need partitioning?     prove the data topology is the bottleneck.
Need Kafka?            only if a genuine event-streaming requirement appears.
                       It probably will not. That is fine.
```

This rule outranks the module order. If you reach Module 9 and your query volume
genuinely does not justify a cache, **skip it and come back** — an unjustified
cache is worse than none, because now you own an invalidation problem you did not
need.

---

# MODULE 1 — Foundation: make it work

Goal: one document in, one cited answer out. Deliberately naive.

### 1.1 — Working synchronous pipeline · **CORE**

| | |
|---|---|
| **Now** | nothing, or the current half-built agent |
| **Trigger** | — this is the starting point |
| **Diagnose** | — |
| **Root cause** | — |
| **Learn** | HTTP, REST, request lifecycle, validation, service/repository layering, the RAG pipeline end to end |
| **Build** | `POST /documents` (sync) → extract → fixed chunking → embed → Qdrant. `POST /query` → embed → top-k → prompt → cited answer. **Record provenance from the first line of code**: every chunk carries its page number, and later its section path and bounding box |
| **Break it** | upload a non-PDF; upload an empty file; ask a question with nothing indexed |
| **Measure** | it answers a question about a 10-page PDF, citing a real page |
| **Next problem** | upload a 300-page PDF: the request hangs for minutes, then the browser times out. Did any of it save? No way to tell |
| **Covers** | HTTP · REST · API design · validation · layering · RAG basics · **provenance** |

> **Provenance is the one thing you cannot add later.** Every other stage in
> this document can be retrofitted onto a running system. Page numbers cannot:
> if extraction discards them, the information is gone and no downstream stage
> can reconstruct it. Citations, evaluation against gold pages, and failure
> attribution all depend on it. Carry `page` through extraction → chunking →
> indexing from day one, even while everything else is deliberately naive.

### 1.2 — Persist what happened · **CORE**

| | |
|---|---|
| **Now** | sync pipeline; the only record a document exists is its chunks in Qdrant |
| **Trigger** | a timed-out upload leaves the system in an unknown state — partially indexed is indistinguishable from not indexed |
| **Diagnose** | count points in Qdrant before and after an interrupted upload |
| **Root cause** | no durable record of intent. The vector index is a *result*, not a log of what was attempted |
| **Learn** | relational modelling, ACID, transactions, indexes, connection pooling, migrations |
| **Build** | Docker Compose + Postgres. `documents`, `ingestion_jobs`. Status lifecycle. Alembic. Repository layer |
| **Break it** | kill the process mid-ingest; confirm the partial state is now *visible* |
| **Measure** | interrupted ingests that are detectable: 0% → 100% |
| **Next problem** | you can see the failure now, but the request still blocks for four minutes |
| **Covers** | DB design · SQL · ACID · transactions · indexes · pooling · migrations · service/repo layering |

### 1.3 — Asynchronous ingestion · **CORE**

| | |
|---|---|
| **Now** | durable records, still synchronous |
| **Trigger** | a 300-page PDF blocks one worker process for four minutes; concurrent uploads make the API unresponsive |
| **Diagnose** | time the request; watch the API stop serving `/health` during ingest |
| **Root cause** | slow, unbounded work is running inside the request/response cycle |
| **Learn** | queues, background workers, producer/consumer, `202 Accepted`, polling vs push |
| **Build** | a job queue (Postgres-backed to start — you do not need Redis yet) + a separate worker process. Upload returns `202` immediately with a job id. `GET /documents/{id}` reports status |
| **Break it** | upload 20 documents at once; confirm the API stays responsive |
| **Measure** | p95 upload response: 240s → <200ms. API availability during bulk ingest: degraded → unaffected |
| **Next problem** | kill the worker mid-job. The document sits at `processing` forever. Nothing retries it |
| **Covers** | queues · workers · async processing · job state · API design (202/polling) |

---

# MODULE 2 — Durable ingestion: make it survive

Goal: the pipeline recovers from its own failures without a human.

### 2.1 — Job lifecycle, leases and retries · **CORE**

| | |
|---|---|
| **Now** | async ingestion; a dead worker orphans its job permanently |
| **Trigger** | `kill -9` a worker mid-job. The document is stuck at `processing` and never recovers |
| **Diagnose** | query for jobs in `processing` older than N minutes |
| **Root cause** | claiming a job is permanent. Nothing distinguishes "in progress" from "abandoned" |
| **Learn** | job state machines, visibility timeout, lease/heartbeat, at-least-once delivery, exponential backoff |
| **Build** | states: `queued → processing → done / failed`. `SELECT ... FOR UPDATE SKIP LOCKED` to claim. A lease with expiry; a reaper that requeues expired leases. Retry with backoff + jitter |
| **Break it** | kill workers repeatedly during a batch; confirm every document eventually reaches a terminal state |
| **Measure** | orphaned jobs after 10 induced crashes: 10 → 0. Time to auto-recovery |
| **Next problem** | the retry re-ran the whole pipeline. The document now has duplicate chunks, and you paid to embed it twice |
| **Covers** | job queues · state machines · leases · `SKIP LOCKED` · retries · backoff · jitter · at-least-once |

### 2.2 — Idempotency · **CORE**

| | |
|---|---|
| **Now** | jobs retry reliably, and retries corrupt data |
| **Trigger** | after a retry, the same fact is cited twice from the same page. Qdrant point count is double what it should be |
| **Diagnose** | compare chunk count to expected; inspect duplicate payloads |
| **Root cause** | the pipeline is not idempotent: re-running it produces new rows rather than replacing old ones |
| **Learn** | idempotency, natural keys, content addressing, deterministic ids, unique constraints, upsert |
| **Build** | SHA-256 content hash on upload → unique per tenant. Deterministic point ids (`uuid5(document_id, chunk_index)`). Delete-then-upsert per document. Idempotency keys on the HTTP layer |
| **Break it** | upload the same file 5× concurrently; retry a job 10×. Chunk count must stay constant |
| **Measure** | duplicate chunks after 10 retries: N → 0. Wasted embedding calls: measured and eliminated |
| **Next problem** | some jobs fail every time — a corrupt PDF, a permanently rejected file. They retry forever, burning quota, and nobody notices |
| **Covers** | idempotency · content addressing · unique constraints · upsert · HTTP idempotency keys |

### 2.3 — Dead-letter queue · **CORE**

| | |
|---|---|
| **Now** | infinite retries on permanently-failing jobs |
| **Trigger** | a malformed PDF retries every 30s for a day. Your embedding quota is consumed by one broken file |
| **Diagnose** | retry counts per job; quota consumption attributable to failing jobs |
| **Root cause** | no distinction between *transient* failure (retry) and *permanent* failure (stop) |
| **Learn** | error classification, poison messages, DLQ, operator tooling, alerting |
| **Build** | max attempts → move to DLQ with the last error and a classification. An endpoint to list, inspect and replay DLQ entries |
| **Break it** | feed in a corrupt PDF, an encrypted PDF, a 0-byte file, a 2GB file |
| **Measure** | wasted retries on poison input: unbounded → ≤3. Mean time to *notice* a failure |
| **Next problem** | all of this is happening invisibly. You only found these bugs because you went looking |
| **Covers** | DLQ · error classification · poison messages · operator tooling |

### 2.4 — Seeing inside · **CORE**

| | |
|---|---|
| **Now** | a reliable pipeline you cannot observe |
| **Trigger** | you cannot answer "is ingestion healthy right now?" without running SQL by hand |
| **Diagnose** | try to answer it. Notice how long it takes |
| **Root cause** | no instrumentation. Logs are unstructured and uncorrelated across API and worker |
| **Learn** | structured logging, correlation IDs, counters vs gauges vs histograms, the RED method. **Learn the distinction now:** `request_id` is *yours* — one inbound API call, propagated by you into the job row. `trace_id` / `span_id` are the tracing system's, and arrive in 10.2. Conflating them is why people bolt on tracing later and find it useless |
| **Build** | JSON logs with a `request_id` threaded API → worker. Counters for jobs by state, histogram for job duration, gauge for queue depth. `/metrics`. **Also: the fake embedder**, behind the provider seam |
| **Break it** | induce a failure and trace it end to end using only the correlation id |
| **Measure** | time to diagnose an induced failure: minutes of manual SQL → seconds |
| **Next problem** | the system is reliable, and the answers are still often wrong. You have no idea how often, or which part is at fault |
| **Covers** | structured logging · correlation IDs · metrics · RED · test doubles |

---

# MODULE 3 — Measurement: stop guessing

**The turning point of the entire project.** Before this you are guessing; after
it every change is evidence-driven. Do not skip it, do not shrink it.

**The eval set is a primary artifact of this project, not a side experiment.** It
is version-controlled, it grows with every new document format and failure mode,
and it is the thing that makes every later claim checkable. Treat it with the
same care as the source code — because every "this improved retrieval by 14%"
you will ever say depends on it.

### 3.1 — Retrieval metrics · **CORE**

| | |
|---|---|
| **Now** | reliable pipeline, unknown quality |
| **Trigger** | you change chunk size. Are answers better? You ask three questions and it "feels" fine. That is not knowledge |
| **Diagnose** | you cannot — that is the problem |
| **Root cause** | no ground truth, so no attribution. "Bad answer" could be extraction, chunking, embedding, retrieval, context or generation |
| **Learn** | ground truth datasets, Recall@K, Precision@K, MRR, nDCG, slicing by question type |
| **Build** | 30–50 hand-written questions over 5–10 real documents, each with a gold answer and the page(s) that contain it. A runner that calls retrieval **directly**, no chatbot in the loop. Metrics, sliced by question type |
| **Break it** | run against a deliberately broken chunker; confirm the metric drops |
| **Measure** | **this stage produces the baseline every later stage is compared against** |
| **Next problem** | recall@5 is 41%. Now: *why?* |
| **Covers** | evaluation · ground truth · IR metrics · experiment design |

### 3.2 — Failure attribution · **CORE**

| | |
|---|---|
| **Now** | a number that says the system is bad, with no cause |
| **Trigger** | recall@5 = 41% and you do not know which layer loses the other 59% |
| **Diagnose** | for each failure, inspect the pipeline output at every stage: did extraction get the text? did a chunk contain the gold span? was it retrieved? was it ranked in the top-k? |
| **Root cause** | failures were being treated as one undifferentiated category |
| **Learn** | failure taxonomies, root-cause attribution, per-layer instrumentation |
| **Build** | a taxonomy (`extraction / chunking / embedding / retrieval / ranking / context / generation`) and a script that labels each failing question automatically where possible, manually where not |
| **Break it** | inject a known fault at each layer; confirm the classifier catches it |
| **Measure** | failures with a named cause: 0% → 100%. A distribution: "60% retrieval, 25% chunking, 15% generation" |
| **Next problem** | the distribution says chunking and retrieval dominate. Now you know exactly what to fix first |
| **Covers** | failure taxonomy · diagnosis · per-layer tracing |

### 3.3 — Answer quality and regression gating · **CORE**

| | |
|---|---|
| **Now** | retrieval is measurable; answer quality is not |
| **Trigger** | retrieval improves but you cannot tell whether *answers* improved |
| **Diagnose** | hand-score 15–20 answers; compare to an LLM judge's scores |
| **Root cause** | no automated answer-quality signal, and no protection against regressions |
| **Learn** | LLM-as-judge, judge calibration, faithfulness vs correctness, regression gates |
| **Build** | a judge, calibrated against your hand scores until it roughly agrees. Citation accuracy. A one-command run that compares to baseline and fails on regression |
| **Break it** | make a change you know is worse; confirm the gate catches it |
| **Measure** | judge/human agreement ≥80% before you trust it |
| **Next problem** | you have a measuring instrument and a ranked list of what is broken. Go fix the biggest one |
| **Covers** | LLM-as-judge · calibration · regression testing · CI for quality |

---

# MODULE 4 — Answer quality

Entered only with a baseline and an attribution distribution in hand. Each stage
is one experiment: hypothesis → change → re-run → keep or delete.

**Work upstream first.** The pipeline is `extract → chunk → embed → retrieve →
rerank → assemble → generate`, and a defect at any stage poisons everything after
it. Tuning chunk size on garbled text is wasted effort. Let the attribution
distribution from 3.2 pick the stage, and when two stages are implicated, fix the
earlier one first.

> **Technique catalogue:** `docs/architecture/system-design.md` §8 lists the full
> ladder for each stage with failure modes and metrics. This module is the
> *sequencing*; that document is the *reference*.

### 4.0 — Extraction quality · **CORE**

| | |
|---|---|
| **Now** | naive text extraction; whatever pypdf returns is treated as truth |
| **Trigger** | attribution says `extraction`. Symptoms: answers quote sentences that read as nonsense; a two-column PDF produces interleaved gibberish; headers and footers appear mid-paragraph; a whole document indexes to almost nothing |
| **Diagnose** | **read the extracted text yourself**, next to the original PDF. This is the one stage where eyeballing beats metrics. Also compare `page_count` against pages that yielded text — a large gap means a scanned document silently indexed as nothing |
| **Root cause** | PDF has no notion of reading order. It is a page-description format: it says "draw this glyph here", not "this paragraph follows that one". A naive extractor emits text in drawing order, which for multi-column layouts interleaves the columns |
| **Learn** | why PDF is not a text format · reading order · layout analysis · boilerplate removal · when to reach for a layout-aware extractor (Docling, unstructured) over a raw text extractor |
| **Build** | whatever the failures justify: strip repeated headers/footers; detect and reject near-empty extractions loudly rather than indexing nothing; move to a layout-aware extractor if multi-column is common in your corpus |
| **Break it** | feed a two-column academic paper, a document with heavy headers/footers, a scanned page, and a form. Each should either extract correctly or **fail loudly** — silent garbage is the enemy |
| **Measure** | extraction failures in attribution: N% → 0. Characters extracted vs expected. Pages yielding no text |
| **Next problem** | the text is clean, and gold spans are still split across chunk boundaries |
| **Covers** | extraction · reading order · layout analysis · document formats · fail-loud design |

### 4.1 — Chunking · **CORE**

| | |
|---|---|
| **Now** | fixed 1200-char chunks, recall@5 = 41% |
| **Trigger** | attribution says chunking. Inspection shows gold spans split across two chunks, and chunks that are meaningless alone ("it rose by 12%" — what did?) |
| **Diagnose** | for each failure, check whether any single chunk fully contains the gold span |
| **Root cause** | character-count splitting ignores document structure |
| **Learn** | chunking strategies, the size/precision tradeoff, structure-aware splitting, overlap economics |
| **Build** | structure-aware chunking (respect headings/paragraphs); table-aware handling; tune size and overlap **as measured experiments, one variable at a time** |
| **Break it** | run each strategy against the same eval set; some will be worse — keep the evidence |
| **Measure** | recall@5, chunk-contains-gold-span %, index size, ingestion time. Write up every experiment, including failures |
| **Next problem** | recall 41% → 75%. Remaining failures are queries with product codes, names, exact phrases |
| **Covers** | chunking · experiment discipline · RAG quality |

**The full chunking ladder.** Structure-aware and table-aware are the CORE rungs;
the rest are here so the map is complete, not so you build them all. Each is
entered only if the failure slice justifies it.

| Rung | What it does | Add when | Rating |
|---|---|---|---|
| Fixed size + overlap | cut every N characters | starting point | CORE |
| **Structure-aware** | respect headings, paragraphs, page boundaries | facts split mid-sentence; chunks span unrelated sections | **CORE** |
| **Table-aware** | a table is one chunk, or row-groups with the header repeated | table questions fail; tables flattened to prose | **CORE** |
| **Parent–child** (small-to-big) | embed small precise chunks, return their larger parent for context | matched chunks are *right* but too small to answer from | **ADV** |
| Contextual | prepend an LLM-written summary of where the chunk sits, before embedding | chunks are meaningless alone ("it rose 12%" — what did?) | ADV |
| Semantic | split where embedding distance shifts, not at a character count | topic boundaries fall mid-chunk | ADV |
| Hierarchical | multi-level summaries: document → section → chunk | a 2,000-page doc needs "which section?" before "which chunk?" | ADV |
| Late chunking | embed the whole document, then pool per-chunk from the full-context embedding | chunk-level embeddings lose document context | OPT |

**Parent–child deserves attention** even though it is ADV: it is the cheapest fix
for the very common case where a 400-character chunk matches perfectly and then
does not contain enough surrounding text to answer from. Retrieve small, return
big.

### 4.2 — Embedding model selection · **ADV**

| | |
|---|---|
| **Now** | one embedding model, chosen on setup convenience rather than evidence |
| **Trigger** | chunking is fixed and recall is still short of where it should be; or you want to know whether the model is leaving quality on the table |
| **Diagnose** | you cannot tell without swapping it — which is exactly why this needs the eval harness first |
| **Root cause** | the embedding model was never a measured decision. It was a default |
| **Learn** | embedding model families, dimensions vs quality, domain fit, the migration cost of changing models, MTEB and why leaderboards mislead on *your* corpus |
| **Build** | 2–3 candidates behind the existing provider seam. Re-embed the corpus for each. **Separate collections**, so you can A/B without destroying the incumbent |
| **Break it** | mix models in one collection deliberately; watch retrieval return nonsense. That failure is why `embedding_model` lives in the chunk payload |
| **Measure** | recall@5 per model on the same eval set · embed cost/1k chunks · embed latency · index size. One table, one winner, written down |
| **Next problem** | the best model still misses exact-token queries — a property of dense embeddings, not of the model |
| **Covers** | embedding models · benchmarking · migration cost · A/B methodology |

> **This is the most expensive experiment in the project.** Every candidate means
> re-embedding the entire corpus, and on a free tier that is slow. Do it once,
> properly, on a corpus you have measured — not on a leaderboard's say-so. Then
> freeze the answer and record it as a decision.

### 4.3 — Hybrid retrieval · **CORE**

| | |
|---|---|
| **Now** | dense-only search, recall@5 = 75% |
| **Trigger** | queries containing exact tokens ("error code X-4021") fail, though the term is in the corpus verbatim |
| **Diagnose** | check whether the gold chunk exists and contains the literal term; confirm it was not retrieved |
| **Root cause** | embeddings capture meaning and lose exact tokens. Rare strings have no semantic neighbourhood |
| **Learn** | lexical vs semantic search, BM25, fusion (RRF), score normalisation |
| **Build** | BM25 alongside dense; fuse with Reciprocal Rank Fusion |
| **Break it** | keyword-only queries, semantic-only queries, mixed. Confirm neither regresses |
| **Measure** | recall@5 overall and **sliced by query type** — the slice is where the win shows |
| **Next problem** | recall@20 is 92%, but recall@5 is 78%. The right chunk is retrieved and then ranked 8th |
| **Covers** | BM25 · hybrid search · rank fusion · IR |

### 4.4 — Reranking · **CORE**

| | |
|---|---|
| **Now** | good candidate generation, poor ordering |
| **Trigger** | large gap between recall@20 and recall@5 |
| **Diagnose** | measure both; the gap *is* the diagnosis |
| **Root cause** | the retriever optimises for speed over precision; nothing re-scores candidates carefully |
| **Learn** | bi-encoder vs cross-encoder, the latency/quality tradeoff, MMR/diversity |
| **Build** | retrieve 50, rerank to 5 with a cross-encoder |
| **Break it** | measure added latency. Decide explicitly whether the quality is worth it |
| **Measure** | nDCG@5, recall@5, **added p95 latency**. The deciding number is quality gained per millisecond |
| **Next problem** | the right chunks are now retrieved and well ordered, and some answers are still wrong |
| **Covers** | reranking · cross-encoders · latency/quality tradeoffs |

### 4.5 — Query transformation · **ADV**

| | |
|---|---|
| **Now** | good retrieval for well-phrased questions |
| **Trigger** | failures concentrate in questions whose wording differs from the document's, and multi-part questions needing two different facts |
| **Diagnose** | slice failures by question type; multi-hop and vocabulary-mismatch will stand out |
| **Root cause** | one query string, one search. No reformulation, no decomposition |
| **Learn** | query rewriting, multi-query, decomposition, HyDE, step-back prompting |
| **Build** | whichever the failure slice justifies — not all of them |
| **Break it** | measure added latency and cost per query; some techniques double both |
| **Measure** | recall on the specific failing slice; total latency; cost/query |
| **Next problem** | evidence is retrieved correctly and the answer still misses parts of it |
| **Covers** | query understanding · multi-hop retrieval |

### 4.6 — Context assembly · **CORE**

| | |
|---|---|
| **Now** | correct chunks retrieved and ranked; answers still incomplete |
| **Trigger** | the gold chunk is in the prompt and the answer ignores it — usually when it sits in the middle of a long context |
| **Diagnose** | log prompt position of the gold chunk against answer correctness |
| **Root cause** | lost-in-the-middle; noise dilution from padding to a fixed k |
| **Learn** | context ordering, token budgeting, relevance thresholds, deduplication, compression |
| **Build** | order strongest evidence first and last; drop below-threshold chunks instead of padding; deduplicate near-identical chunks; budget tokens explicitly |
| **Break it** | force 20 chunks into the prompt; measure the quality drop. More context is not better |
| **Measure** | answer correctness vs k; correctness vs gold-chunk position; tokens/query |
| **Next problem** | quality is respectable. Then a second person starts using it — and sees your documents |
| **Covers** | context engineering · prompt construction · lost-in-the-middle |

---

# MODULE 5 — Multi-user

### 5.1 — Tenancy and isolation · **CORE**

| | |
|---|---|
| **Now** | single shared index; every document visible to everyone |
| **Trigger** | user B asks a question and gets an answer citing user A's document |
| **Diagnose** | index a document as A, query as B, observe the leak |
| **Root cause** | no ownership on data and no filter at query time |
| **Learn** | multi-tenancy models (shared table + filter vs schema vs database), data isolation, defence in depth |
| **Build** | `tenant_id` on every row and every chunk payload. A hard metadata filter on **every** vector query, derived from the caller — never from a prompt |
| **Break it** | **the adversarial test**: put a unique token in A's corpus; try every prompt you can invent as B to surface it |
| **Measure** | cross-tenant leaks across N adversarial attempts: must be 0 |
| **Next problem** | there is a `tenant_id`, and anyone can claim to be any tenant |
| **Covers** | multi-tenancy · data isolation · authorization at the data layer |

### 5.2 — Authentication · **CORE**

| | |
|---|---|
| **Now** | tenancy enforced, identity unverified |
| **Trigger** | `curl` with someone else's tenant id returns their data |
| **Diagnose** | do exactly that |
| **Root cause** | identity is claimed by the client rather than proven |
| **Learn** | authn vs authz, sessions vs tokens, password storage, cookie security, API keys |
| **Build** | session cookies (httpOnly, SameSite) for the browser; API keys for programmatic access; a `current_user` dependency. Internal service token for backend → agent |
| **Break it** | forged cookie, expired session, missing header, token from a deleted user |
| **Measure** | unauthorized access attempts blocked: 100%. Auth overhead per request |
| **Next problem** | one user uploads 500 documents and everyone else's ingestion stops |
| **Covers** | authentication · sessions · API keys · cookie security |

### 5.3 — Authorization and audit · **ADV**

| | |
|---|---|
| **Now** | authenticated users, all-or-nothing access |
| **Trigger** | you need a shared document, or read-only access, or "who deleted that?" |
| **Diagnose** | try to answer "who did what, when" from your logs |
| **Root cause** | no permission model and no audit trail |
| **Learn** | RBAC, ACL inheritance, audit logging, derived-data permissions |
| **Build** | roles; document-level ACLs; derived chunks inherit the source document's ACL; an append-only audit log |
| **Break it** | revoke access mid-query; confirm chunks stop being retrievable immediately |
| **Measure** | permission-change propagation time; audit completeness |
| **Next problem** | — |
| **Covers** | authorization · RBAC · ACL · audit |

---

# MODULE 6 — Contention

**This module exists because RAG does not naturally produce high-contention
concurrency.** Quotas are the honest way to create it: embeddings genuinely cost
money and providers genuinely rate-limit, so every real platform has this.

### 6.1 — Quotas and atomic reservation · **CORE**

| | |
|---|---|
| **Now** | unlimited embedding spend per tenant |
| **Trigger** | one tenant's bulk upload exhausts the shared provider quota; every other tenant's ingestion fails |
| **Diagnose** | attribute embedding calls per tenant; correlate with others' failures |
| **Root cause** | a shared finite resource with no accounting and no admission control |
| **Learn** | shared mutable state, atomic operations, the read-modify-write race, reservation patterns |
| **Build** | per-tenant token budget. A job must **reserve** before embedding and **release or commit** after. Start with the naive `SELECT` then `UPDATE` |
| **Break it** | 50 concurrent workers against a budget of 100. **The naive version will oversell** — prove it |
| **Measure** | overspend under concurrency: measurable → 0 |
| **Next problem** | you fixed it with a lock. Throughput collapsed |
| **Covers** | shared state · race conditions · atomicity · reservation |

### 6.2 — Isolation anomalies: a laboratory · **CORE**

**The most transferable stage in the project.** "I know optimistic locking" is a
claim. "I reproduced write skew at READ COMMITTED, fixed it at SERIALIZABLE, and
measured the throughput cost" is evidence.

| | |
|---|---|
| **Now** | you have one proven race (quota oversell) and no idea which *class* of anomaly it is |
| **Trigger** | 6.1 oversold the budget. Why exactly? What does Postgres actually guarantee by default — and what does it not? |
| **Diagnose** | two psql sessions side by side, statements interleaved by hand. Watch the anomaly happen in slow motion before you automate it |
| **Root cause** | Postgres defaults to READ COMMITTED, which permits several anomalies people assume are impossible |
| **Learn** | the anomaly catalogue and which isolation level prevents each |
| **Build** | a reproducible test per anomaly. Each one: (a) demonstrate it, (b) fix it, (c) measure the fix's cost |
| **Break it** | each anomaly below must be reproduced **as a failing automated test** before you fix it |
| **Measure** | for each: does it occur at READ COMMITTED / REPEATABLE READ / SERIALIZABLE? Throughput and serialization-failure rate at each level |
| **Next problem** | you now know which level is correct, and the correct one is slow. How else can you get correctness? |
| **Covers** | isolation levels · ACID in practice · MVCC · the anomaly catalogue · locking vs isolation |

**The anomalies, each with a natural home in this system:**

| Anomaly | Reproduce with | Notes |
|---|---|---|
| **Dirty read** | try it — Postgres will *not* let you | READ UNCOMMITTED is an alias for READ COMMITTED here. Learning that it is unreachable is itself the lesson |
| **Lost update** | two workers read quota 100, both subtract 30, both write 70 | the classic read-modify-write race from 6.1 |
| **Non-repeatable read** | read a document's status twice in one transaction while another commits a change between | REPEATABLE READ fixes it |
| **Phantom read** | `COUNT(*)` chunks for a document twice while another inserts more | the row that appears from nowhere |
| **Write skew** | two tenants share a pool; each job checks "is total usage < limit?", both see OK, both proceed, the sum exceeds the limit | **the interesting one** — no row is written twice, every read is consistent, and the invariant still breaks. Only SERIALIZABLE (or an explicit lock/constraint) prevents it |

**Write skew deserves the most attention.** It is the anomaly that survives
REPEATABLE READ, it is invisible to people who think "I used a transaction, so I
am safe", and your quota system produces it naturally. Reproduce it, then fix it
three different ways — SERIALIZABLE, a materialised counter with a CHECK
constraint, and an explicit lock — and measure all three.

### 6.3 — Optimistic vs pessimistic concurrency · **CORE**

| | |
|---|---|
| **Now** | correct quota accounting, serialised throughput |
| **Trigger** | with a row lock, 50 workers process one at a time; throughput drops ~10× |
| **Diagnose** | measure throughput with and without the lock; observe lock wait time |
| **Root cause** | pessimistic locking serialises all contenders regardless of conflict |
| **Learn** | optimistic vs pessimistic locking, CAS, version columns, retry storms, isolation levels, deadlocks |
| **Build** | version column + compare-and-swap + bounded retry. Compare against `SELECT FOR UPDATE`, against an atomic `UPDATE ... SET x = x - n WHERE x >= n`, and against a Redis atomic counter |
| **Break it** | push contention until CAS retry rate exceeds 40%; watch throughput collapse *differently*. Induce a deadlock deliberately |
| **Measure** | throughput, p99 latency and retry rate for each strategy, at 5 / 50 / 500 concurrent actors. **This table is a great interview artifact** |
| **Next problem** | quota is safe. Now two workers re-index the same document simultaneously and the index ends up mixed |
| **Covers** | optimistic/pessimistic locking · CAS · isolation levels · deadlocks · retry storms |

### 6.4 — Distributed locks, leases and fencing · **ADV**

| | |
|---|---|
| **Now** | row-level concurrency solved; multi-step operations spanning two datastores unprotected |
| **Trigger** | two re-index jobs for one document interleave. The index ends up holding chunks from both runs |
| **Diagnose** | reproduce with two workers and a deliberate pause between delete and upsert |
| **Root cause** | a multi-step operation across Postgres and Qdrant has no mutual exclusion — **and a lock alone cannot fix it**, because a lock can expire while its holder is still alive and still about to write |
| **Learn** | distributed locks, lease expiry, the **stale lock-holder problem**, fencing tokens, why "I held the lock" is not the same as "I still hold the lock" |
| **Build** | see the sequence below |
| **Break it** | the GC-pause simulation below. Without fencing it corrupts; with fencing the stale write is rejected |
| **Measure** | corrupted indexes across 100 induced interleavings: N → 0. Also: how often the reject path fires, and whether stale workers clean up after themselves |
| **Next problem** | correct under concurrency. Then the embedding provider starts failing |
| **Covers** | distributed locks · leases · fencing tokens · cross-system consistency · why locks are insufficient |

**The exact sequence you must make safe:**

```text
Worker A acquires the lease, gets token 41
Worker A pauses          (GC pause, VM suspend, network partition — pick one)

        lease expires

Worker B acquires the lease, gets token 42
Worker B writes its chunks                       ← legitimate, current owner

Worker A wakes up, still believing it holds the lease
Worker A attempts to write with token 41
                    ↓
            MUST BE REJECTED
```

**The error I want you to avoid:** do not assume the vector store will enforce
this. **Qdrant has no conditional write** — no compare-and-set, no "reject if
version < N". Hand it a stale write and it will cheerfully accept it. Any design
that says "Redis issues a fencing token and Qdrant checks it" is wrong.

So the real exercise is deciding **where the authoritative check lives**, and the
only place you have atomicity is Postgres:

```text
documents.index_generation   monotonically increasing, owned by Postgres

acquiring the lease   →  UPDATE documents
                         SET index_generation = index_generation + 1
                         WHERE id = ?
                         RETURNING index_generation        ← this is the token

before committing     →  UPDATE documents
                         SET indexed_generation = :token
                         WHERE id = ? AND index_generation = :token
                         
                         0 rows affected  →  you are stale. Abort.
                                             Delete anything you wrote. Do not retry blindly.
```

The vector write becomes the *uncommitted* part, and Postgres holds the commit
point. A stale worker can still write garbage to Qdrant — what it cannot do is
mark that garbage authoritative, and the next successful run overwrites it by
deterministic point id (stage 2.2).

**The transferable lesson is not "Redis plus Qdrant".** It is:

> A worker that has lost ownership must be unable to commit — and the check has
> to happen at a point where something can enforce atomicity. If your storage
> layer cannot do conditional writes, the commit point must move somewhere that
> can.

That idea generalises to every distributed system you will ever work on, and it
is a genuinely good interview answer.

**Worth also proving to yourself:** what happens with *no* fencing, only a lease?
Build that first, reproduce the corruption, and only then add the token. The
corruption is the point.

---

# MODULE 7 — Resilience

### 7.1 — Timeouts and retry discipline · **CORE**

| | |
|---|---|
| **Now** | external calls with default (or no) timeouts |
| **Trigger** | the embedding provider gets slow. Workers hang for minutes. The queue backs up with nothing visibly failing |
| **Diagnose** | latency histogram per external dependency; count workers in-flight |
| **Root cause** | no timeout means a slow dependency is worse than a dead one — it consumes capacity indefinitely |
| **Learn** | timeouts (connect vs read vs total), retry budgets, jitter, the thundering herd |
| **Build** | explicit timeouts everywhere. Retries with exponential backoff **and jitter**. A retry budget so retries cannot exceed a fraction of traffic |
| **Break it** | a proxy that delays responses by 30s; another that drops connections mid-body |
| **Measure** | p99 job duration under induced slowness; worker utilisation; retry amplification factor |
| **Next problem** | the provider goes fully down. Every job retries, fails, retries — you are DDoSing a dead service and burning your own capacity |
| **Covers** | timeouts · backoff · jitter · retry budgets |

### 7.2 — Circuit breaker · **CORE**

| | |
|---|---|
| **Now** | disciplined retries, still hammering a dead dependency |
| **Trigger** | provider returns 100% errors; your system spends all capacity retrying |
| **Diagnose** | error rate per dependency; ratio of retry traffic to new traffic |
| **Root cause** | no concept of "this dependency is down; stop trying for a while" |
| **Learn** | circuit breaker states (closed/open/half-open), failure thresholds, recovery probing |
| **Build** | a breaker around each external provider. Open on threshold; reject fast; half-open probe to recover |
| **Break it** | kill the provider (point it at a black hole); confirm the breaker opens, the queue stops churning, and recovery is automatic when it returns |
| **Measure** | wasted calls during a 5-minute outage: thousands → tens. Recovery time after restoration |
| **Next problem** | embedding is circuit-broken, and query traffic is also failing — one dependency took down an unrelated feature |
| **Covers** | circuit breakers · fail-fast · dependency isolation |

### 7.3 — Bulkheads and graceful degradation · **ADV**

| | |
|---|---|
| **Now** | one failing dependency degrades everything |
| **Trigger** | the embedding provider is down, and *queries* also fail — though answering from an existing index needs no ingestion |
| **Diagnose** | map which code paths share a connection pool, thread pool or worker pool |
| **Root cause** | shared resource pools couple unrelated failure domains |
| **Learn** | bulkhead pattern, resource partitioning, failure domains, degradation modes |
| **Build** | separate pools/concurrency limits for ingestion vs query. Define what "degraded" means: queries serve from the existing index; ingestion is paused and queued |
| **Break it** | take down each dependency in turn; confirm only the dependent feature degrades |
| **Measure** | query availability during an embedding outage: 0% → ~100% |
| **Next problem** | the system survives failures. Now it drowns in success |
| **Covers** | bulkheads · failure domains · graceful degradation |

---

# MODULE 8 — Overload

### 8.1 — Backpressure · **CORE**

| | |
|---|---|
| **Now** | unbounded queue |
| **Trigger** | ingestion accepts 10k jobs while embedding drains 1k. Queue depth grows without limit; memory climbs; jobs sit for hours |
| **Diagnose** | queue depth over time; arrival rate vs service rate (Little's Law) |
| **Root cause** | the producer has no feedback from the consumer |
| **Learn** | backpressure, Little's Law, bounded queues, admission control, load shedding |
| **Build** | bounded queue. When full: reject with `429` and `Retry-After` rather than accept-and-die. Surface queue depth and estimated wait |
| **Break it** | generate 10× the drain rate; confirm bounded memory and honest rejections |
| **Measure** | memory under sustained overload: unbounded → flat. Rejection rate vs queue wait time |
| **Next problem** | fair rejection, but one aggressive client still consumes the whole queue |
| **Covers** | backpressure · bounded queues · load shedding · Little's Law |

### 8.2 — Rate limiting · **CORE**

| | |
|---|---|
| **Now** | global admission control, no per-client fairness |
| **Trigger** | one client's script fills the queue; everyone else is rejected |
| **Diagnose** | request rate per client; queue occupancy by tenant |
| **Root cause** | admission control is global, not per-identity |
| **Learn** | token bucket vs leaky bucket vs sliding window, distributed rate limiting, fairness |
| **Build** | per-tenant and per-endpoint limits in Redis. Correct `429` + `Retry-After` + limit headers |
| **Break it** | burst traffic from one tenant; confirm others are unaffected. Run two API instances and confirm the limit is shared, not doubled |
| **Measure** | throughput of a well-behaved tenant while another floods: degraded → unaffected |
| **Next problem** | protected and fair, and the database starts refusing connections under load |
| **Covers** | rate limiting · token bucket · distributed counters · fairness |

### 8.3 — Resource exhaustion · **CORE**

| | |
|---|---|
| **Now** | more concurrency than the datastore can serve |
| **Trigger** | under load: `too many clients already`, or requests queueing invisibly on pool checkout |
| **Diagnose** | pool utilisation, checkout wait time, active DB connections |
| **Root cause** | connection pools sized without regard to DB limits or worker count |
| **Learn** | connection pooling maths, pool sizing, queueing on checkout, file descriptors, PgBouncer |
| **Build** | size pools deliberately (workers × pool size ≤ DB max). Checkout timeouts. Pool metrics |
| **Break it** | deliberately over-provision workers; watch it fail; fix by sizing |
| **Measure** | error rate at 2×/5×/10× load before and after; pool wait p99 |
| **Next problem** | stable under load and slow. The same question is asked 50× a day and re-computed every time |
| **Covers** | connection pooling · resource limits · capacity |

---

# MODULE 9 — Caching

### 9.1 — Cache-aside · **CORE**

| | |
|---|---|
| **Now** | every query re-embeds and re-searches |
| **Trigger** | repeated identical questions; embedding cost and p95 latency both dominated by work already done |
| **Diagnose** | distribution of repeated queries; latency breakdown by stage |
| **Root cause** | deterministic, expensive, repeated computation with no memoisation |
| **Learn** | cache-aside, TTL, key design, hit rate, what is safely cacheable |
| **Build** | Redis. Cache query embeddings (content-addressed, effectively immutable) and retrieval results (TTL'd). **Keys must include tenant** |
| **Break it** | confirm a cache miss and a hit produce identical results. Confirm tenant A never reads tenant B's cached entry |
| **Measure** | p95 query latency, cache hit rate, embedding calls/query |
| **Next problem** | a document is re-indexed and the cache keeps serving the old answer |
| **Covers** | caching · cache-aside · TTL · key design |

### 9.2 — Invalidation · **CORE**

| | |
|---|---|
| **Now** | cached results that outlive their source data |
| **Trigger** | re-index a document; queries still return pre-update answers until TTL expiry |
| **Diagnose** | update a document, query immediately, compare |
| **Root cause** | no link between source-data mutation and cached derivatives |
| **Learn** | invalidation strategies, versioned keys, the correctness/complexity tradeoff, eventual consistency |
| **Build** | version-stamped cache keys per document/tenant — bump the version on re-index rather than hunting individual keys |
| **Break it** | re-index under concurrent query load; measure the stale window |
| **Measure** | stale-answer window: TTL (minutes) → near-zero |
| **Next problem** | a popular entry expires and 200 requests recompute it simultaneously |
| **Covers** | cache invalidation · versioned keys · eventual consistency |

### 9.3 — Multi-document invalidation · **CORE**

**The best pure system-design problem in the project.** Single-document
invalidation was easy. This one has no clean answer, only tradeoffs — which is
exactly why it is worth doing.

| | |
|---|---|
| **Now** | version-stamped keys per document, which works when a cached thing depends on *one* document |
| **Trigger** | a cached **answer** was built from documents A v7, B v12 and C v4. Only B changes. The cached answer is now wrong — and its key mentions no document at all, because the key is a hash of the *question* |
| **Diagnose** | cache an answer drawing on three documents; update one; query again; observe the stale answer and notice you have no mechanism that could have known |
| **Root cause** | the cache key is derived from the **input** (the question), but validity depends on the **output's dependencies** (whichever chunks happened to be retrieved) — which are not known until after the expensive work is done |
| **Learn** | dependency-aware invalidation, generation counters, the precision/complexity tradeoff, bounded staleness as a deliberate choice |
| **Build** | implement **at least two** of the strategies below and measure both |
| **Break it** | update one document in a 10k-document corpus; count how many cache entries were invalidated versus how many actually needed to be |
| **Measure** | stale-answer window · invalidation precision (necessary evictions ÷ total evictions) · hit rate under a realistic write rate |
| **Next problem** | correct invalidation, and a popular entry still causes a thundering herd at expiry |
| **Covers** | cache invalidation · dependency tracking · eventual consistency · bounded staleness · tradeoff analysis |

**The three real options:**

| Strategy | How | Precision | Cost |
|---|---|---|---|
| **Corpus generation counter** | one counter per tenant, bumped on *any* write; it is part of every cache key | terrible — one upload evicts everything | trivial to build, and often correct anyway |
| **Dependency tracking** | store, with each cached answer, the document ids and versions it used. On a document write, evict entries listing it (a reverse index) | exact | a second index to maintain, and it can be larger than the cache |
| **TTL + accept staleness** | short TTL, no invalidation, documented staleness window | none, by design | free — and the right answer more often than engineers like to admit |

**The point of the exercise is the argument, not the code.** Be able to say:
*"We chose a per-tenant generation counter. Writes are rare relative to reads —
measured at 1:400 — so over-invalidation costs us about 3% of hit rate, and it
removed an entire class of correctness bug. Dependency tracking would have been
exact, but the reverse index would exceed the cache itself, and for an
unmeasurable quality gain."*

That is a system-design interview answer. "I used Redis with a TTL" is not.

---

### 9.4 — Stampede and hot keys · **ADV**

| | |
|---|---|
| **Now** | correct caching with pathological expiry behaviour |
| **Trigger** | at expiry, a latency spike and a burst of identical expensive work |
| **Diagnose** | latency spikes correlated with TTL boundaries; duplicate in-flight computations |
| **Root cause** | nothing coordinates concurrent misses on the same key |
| **Learn** | cache stampede, single-flight, probabilistic early expiry, hot keys, cache penetration |
| **Build** | single-flight per key (lock or promise sharing); jittered TTLs; negative caching for known-missing keys |
| **Break it** | 200 concurrent requests for one key at the moment of expiry |
| **Measure** | duplicate computations per expiry: 200 → 1. Spike magnitude |
| **Next problem** | Redis itself goes down. Everything fails, though a cache should be optional |
| **Covers** | stampede · single-flight · hot keys · negative caching |

### 9.5 — Cache as an optional dependency · **ADV**

| | |
|---|---|
| **Now** | Redis is a hard dependency |
| **Trigger** | stop Redis; the whole API errors |
| **Diagnose** | kill Redis and watch |
| **Root cause** | cache failures are not handled as cache *misses* |
| **Learn** | optional dependencies, fail-open vs fail-closed, degraded modes |
| **Build** | treat Redis errors as misses for caching; decide deliberately for rate limiting (fail-open risks abuse, fail-closed risks outage — **pick, and write down why**) |
| **Break it** | run the full test suite with Redis down |
| **Measure** | availability with Redis down: 0% → ~100% (slower) |
| **Next problem** | resilient and hard to reason about. Something is slow and you cannot say what |
| **Covers** | optional dependencies · fail-open/closed · degradation |

---

# MODULE 10 — Observability in depth

**End of the job-ready checkpoint.** With modules 1–10 done properly you can hold
a serious backend interview.

### 10.1 — Metrics and dashboards · **CORE**

| | |
|---|---|
| **Now** | scattered counters, no overview |
| **Trigger** | "is the system healthy?" takes ten minutes and several terminals |
| **Diagnose** | time yourself answering it |
| **Root cause** | metrics exist but are not aggregated or visualised |
| **Learn** | RED (rate/errors/duration), USE (utilisation/saturation/errors), cardinality, dashboards |
| **Build** | Prometheus + Grafana. RED per endpoint; USE per pool; pipeline stage timings; cost per query |
| **Break it** | induce four different faults; identify each from the dashboard alone, without reading logs |
| **Measure** | time to identify a fault class: minutes → seconds |
| **Next problem** | you can see *that* p99 is 4s; you cannot see *where* those 4 seconds go |
| **Covers** | metrics · RED/USE · dashboards · cardinality |

### 10.2 — Distributed tracing · **CORE**

| | |
|---|---|
| **Now** | per-service metrics, no per-request causality |
| **Trigger** | a slow request crosses API → queue → worker → embedding → vector store; aggregates cannot attribute the latency |
| **Diagnose** | try to reconstruct one slow request from logs across three processes |
| **Root cause** | no trace context propagated across process and queue boundaries |
| **Learn** | tracing, spans, context propagation (including **through a queue**), sampling. The full picture you are building: `HTTP request → trace/span → queue message (carrying trace context) → worker span → embedding span → vector-DB span`. A trace that stops at the queue boundary is the common failure, and the async hop is exactly the interesting part |
| **Build** | OpenTelemetry end to end. Trace id carried in job payloads so async work joins the same trace |
| **Break it** | inject latency at a random stage; find it from the trace in under a minute |
| **Measure** | time to localise a latency source; trace completeness across async boundaries |
| **Next problem** | you can see everything. Now make it fast |
| **Covers** | tracing · context propagation · sampling |

### 10.3 — SLOs and alerting · **ADV**

| | |
|---|---|
| **Now** | full visibility, no definition of "acceptable" |
| **Trigger** | you cannot say whether today was a good day |
| **Diagnose** | try to define "healthy" numerically |
| **Root cause** | no service level objectives |
| **Learn** | SLI/SLO/SLA, error budgets, alerting on symptoms not causes, alert fatigue |
| **Build** | SLOs (query p95, ingestion success rate, availability). Alerts on SLO burn, not on CPU |
| **Break it** | breach each SLO deliberately; confirm exactly one useful alert fires |
| **Measure** | alert precision: false alarms per real incident |
| **Next problem** | — |
| **Covers** | SLO/SLI · error budgets · alerting |

---

# MODULE 11 — Performance engineering · **CORE**

### 11.1 — Load testing harness

| | |
|---|---|
| **Now** | measured functionally, never under load |
| **Trigger** | you cannot answer "how many concurrent users can this take?" |
| **Diagnose** | — |
| **Root cause** | no repeatable load generation |
| **Learn** | open vs closed workload models, warm-up, percentiles vs averages, coordinated omission |
| **Build** | k6 or Locust. Realistic mixed workload. **Fake embedder** so load tests do not hit provider quota |
| **Break it** | ramp until something breaks; record what broke first |
| **Measure** | the saturation point. Throughput and p50/p95/p99 vs concurrency |
| **Next problem** | you know it breaks at N. You do not know why |
| **Covers** | load testing · percentiles · workload modelling |

### 11.2 — Bottleneck isolation

| | |
|---|---|
| **Now** | a known breaking point, unknown cause |
| **Trigger** | at 200 rps, p99 explodes |
| **Diagnose** | USE metrics per resource; flame graphs; per-stage timings |
| **Root cause** | whatever it turns out to be — and it is usually not what you guessed |
| **Learn** | profiling, Amdahl's law, queueing theory basics, the one-variable rule |
| **Build** | fix exactly one bottleneck, re-measure, repeat. Keep a log of every hypothesis, including the wrong ones |
| **Break it** | predict the *next* bottleneck before measuring; check whether you were right |
| **Measure** | throughput per change. **A table of "changed X → throughput Y → because Z" is the single best interview artifact this project produces** |
| **Next problem** | one machine is optimised. The limit is now the machine |
| **Covers** | profiling · bottleneck analysis · capacity |

### 11.3 — Database performance

| | |
|---|---|
| **Now** | DB is the bottleneck |
| **Trigger** | slow queries under load; lock contention; sequential scans |
| **Diagnose** | `EXPLAIN ANALYZE`, `pg_stat_statements`, lock views |
| **Root cause** | missing/wrong indexes, N+1 queries, over-broad transactions |
| **Learn** | query plans, index types, selectivity, transaction scope, N+1 |
| **Build** | indexes justified by plans; narrowed transaction boundaries; batched writes |
| **Break it** | drop an index and measure the damage; understand the number |
| **Measure** | query p99 before/after per fix; rows examined vs returned |
| **Next problem** | — |
| **Covers** | SQL performance · indexes · query plans · transaction scope |

---

# MODULE 12 — Horizontal scale · **CORE**

### 12.1 — Stateless services and load balancing

| | |
|---|---|
| **Now** | one API process |
| **Trigger** | a restart is downtime; one core is the ceiling |
| **Diagnose** | deploy and watch requests fail |
| **Root cause** | in-process state and a single instance |
| **Learn** | statelessness, session externalisation, load balancing, health checks, sticky-session pitfalls |
| **Build** | remove in-process state (that in-memory conversation dict finally dies here). N instances behind a load balancer. Real readiness/liveness endpoints |
| **Break it** | kill one instance under load; measure dropped requests. Confirm no request depends on hitting the same instance twice |
| **Measure** | requests lost during instance failure: N → ~0. Throughput vs instance count (is it linear? why not?) |
| **Next problem** | the API scales; the workers do not coordinate |
| **Covers** | statelessness · load balancing · health checks · horizontal scaling |

### 12.2 — Worker scaling and coordination

| | |
|---|---|
| **Now** | multiple API instances, worker pool unexamined |
| **Trigger** | adding workers stops improving throughput, or starts causing errors |
| **Diagnose** | throughput vs worker count; DB connections; provider rate limits |
| **Root cause** | a shared downstream limit — pool, provider quota, or lock contention |
| **Learn** | scaling limits, coordination cost, the shared-bottleneck principle |
| **Build** | tune worker concurrency against the real constraint; distribute provider quota across workers |
| **Break it** | over-scale deliberately; find where it gets *worse* |
| **Measure** | throughput vs worker count curve; locate and explain the knee |
| **Next problem** | compute scales. Data does not |
| **Covers** | worker pools · scaling limits · coordination |

### 12.3 — Zero-downtime deployment · **ADV**

| | |
|---|---|
| **Now** | deploys drop requests and may break in-flight jobs |
| **Trigger** | deploy under load; watch errors, and find a job killed mid-flight |
| **Diagnose** | error rate during deploy; jobs left in `processing` |
| **Root cause** | no graceful shutdown; no rolling strategy; schema changes not backward compatible |
| **Learn** | rolling/blue-green/canary, graceful shutdown, drain, expand-contract migrations |
| **Build** | SIGTERM handling that finishes or releases current work. Rolling deploy. Backward-compatible migrations in two phases |
| **Break it** | deploy a schema change under load with old and new code running simultaneously |
| **Measure** | errors during deploy: N → 0. Jobs lost per deploy: N → 0 |
| **Next problem** | — |
| **Covers** | deployment strategies · graceful shutdown · schema migration |

---

# MODULE 13 — Data at scale · **ADV**

Mostly reasoning plus synthetic workloads. You will not operate a real 10M-document
cluster, and pretending otherwise teaches nothing.

### 13.0 — Documents are not vectors · **CORE**

**Do this before any scaling experiment.** "10M documents" is not a scale unit —
it is an input to one. Getting this conversion wrong is how people design for the
wrong system by two orders of magnitude.

| | |
|---|---|
| **Now** | a vague target of "10M documents" |
| **Trigger** | try to answer "how much RAM does the index need?" and notice you cannot, because you never converted documents into vectors |
| **Diagnose** | measure your *own* corpus: pages per document, chunks per page, bytes per chunk |
| **Root cause** | the unit of scale for a vector store is the **vector**, and one document produces tens to hundreds of them |
| **Learn** | unit conversion chains, fan-out factors, back-of-envelope estimation, quantization economics |
| **Build** | a written model, measured from your real corpus, not guessed |
| **Break it** | have someone challenge each assumption — this is a system-design interview rehearsal |
| **Measure** | predicted vs actual at 100k chunks, so you know your model's error before extrapolating 10,000× |
| **Next problem** | the number is large enough that index configuration is now an architectural decision, not a tuning detail |
| **Covers** | capacity estimation · fan-out · quantization tradeoffs · system design |

**The chain you must be able to walk in both directions:**

```text
documents → pages/doc → chunks/page → total chunks
          → dimensions → bytes/vector → raw size
          → + index overhead → + text payload → RAM & disk
          → nodes required → query throughput per node
```

**Worked example, 768 dimensions:**

| Docs | Pages/doc | Chunks/page | Total vectors |
|---:|---:|---:|---:|
| 10M | 10 | 2 | **0.2B** |
| 10M | 20 | 2.5 | **0.5B** |
| 10M | 50 | 2 | **1.0B** |

| Encoding | Bytes/vector | 500M vectors | 1B vectors |
|---|---:|---:|---:|
| float32 (raw) | 3,072 | 1.40 TB | 2.79 TB |
| float16 | 1,536 | 0.70 TB | 1.40 TB |
| int8 scalar quant | 768 | 0.35 TB | 0.70 TB |
| binary quant | 96 | **0.04 TB** | **0.09 TB** |

Plus HNSW graph overhead (roughly +50–100%) and the chunk text itself
(500M × ~1.2 KB ≈ 0.55 TB, which usually belongs in object storage or Postgres
rather than in the vector store's memory).

**Why this matters more than it looks:** at float32 this is a multi-terabyte,
multi-node, "we need a team" problem. At binary quantization it fits on a handful
of machines. That is a 30× architectural difference — and it is completely
invisible if you only ever say "10M documents".

**So the honest claim to practise is:** *"We measured 50 chunks per document on
our corpus. At 10M documents that is 500M vectors; at 768 dims int8 that is
~350 GB of vectors plus graph overhead, so roughly N nodes at M GB each. Our
100k-chunk experiment measured X ms p99, which extrapolates to Y."*

---

### 13.1 — Vector index scaling

| | |
|---|---|
| **Now** | one collection, modest size |
| **Trigger** | synthetically load 10M **chunks** (per 13.0, that is only ~200k documents — a useful reminder of the fan-out): search latency and memory both degrade |
| **Diagnose** | latency vs collection size; memory per vector; recall vs speed |
| **Root cause** | ANN index parameters and memory footprint scale with data |
| **Learn** | HNSW parameters, quantization, recall/speed/memory tradeoffs, index build cost |
| **Build** | tune HNSW; scalar/binary quantization; measure the recall cost |
| **Break it** | quantize aggressively; measure the retrieval quality you lost |
| **Measure** | search p99 and memory vs index size and settings; recall@5 delta from quantization |
| **Next problem** | one index cannot hold everything |
| **Covers** | ANN indexes · quantization · memory/quality tradeoffs |

### 13.2 — Partitioning and sharding

| | |
|---|---|
| **Now** | single index, single DB |
| **Trigger** | index exceeds one node; one large tenant dominates |
| **Diagnose** | size and traffic distribution per tenant; identify hot partitions |
| **Root cause** | no partition key; all load on one physical resource |
| **Learn** | partition key selection, hot partitions, rebalancing, fan-out queries, Postgres partitioning |
| **Build** | partition by tenant (with a plan for the tenant too large for one shard). Time-partition large tables. Document the routing |
| **Break it** | simulate a tenant 100× larger than the rest; observe hot-partition behaviour |
| **Measure** | p99 with/without hot partitions; storage and query distribution |
| **Next problem** | reads dominate; writes are fine |
| **Covers** | partitioning · sharding · hot partitions · partition keys |

### 13.3 — Replication and read scaling

| | |
|---|---|
| **Now** | single primary serving reads and writes |
| **Trigger** | read load saturates the primary |
| **Diagnose** | read/write ratio; primary CPU; replication lag once replicas exist |
| **Root cause** | reads and writes contending for one resource |
| **Learn** | replication, read replicas, replication lag, read-your-writes, consistency models |
| **Build** | read replica; route read-only queries to it; identify which reads **cannot** tolerate lag |
| **Break it** | write then immediately read from a replica; observe the stale read. Decide which paths must hit the primary |
| **Measure** | primary load reduction; replication lag distribution; stale-read frequency |
| **Next problem** | — |
| **Covers** | replication · read replicas · eventual consistency · read-your-writes |

### 13.4 — Capacity planning

| | |
|---|---|
| **Now** | measured system, no forward model |
| **Trigger** | "what does 10M documents cost, and what breaks first?" |
| **Diagnose** | extrapolate from measured per-unit costs |
| **Root cause** | — this stage is reasoning, not repair |
| **Learn** | capacity modelling, cost per unit, growth projection, headroom |
| **Build** | a written model: storage/doc, embedding cost/doc, query cost, memory/vector. Project to 10M. Name the first thing to break |
| **Break it** | have someone challenge your assumptions — this is a system-design interview rehearsal |
| **Measure** | predicted vs actual at a scale you *can* test (say 100k); check your model's error |
| **Next problem** | — |
| **Covers** | capacity planning · cost modelling · system design |

---

# MODULE 14 — Event-driven architecture · **ADV**

**Honest warning:** this project may never produce a genuine need for events. Enter
only when you have two or more consumers that must react to the same fact. If you
build it "for the learning", say so out loud and do not claim it was justified.

### 14.1 — The outbox pattern

| | |
|---|---|
| **Now** | side effects performed inline after a DB commit |
| **Trigger** | a document commits, then the notification/cache-invalidation/analytics step fails. The DB and the side effect disagree |
| **Diagnose** | kill the process between commit and side effect; observe divergence |
| **Root cause** | the dual-write problem: two systems, no shared transaction |
| **Learn** | dual-write, outbox, transactional guarantees across systems, at-least-once delivery |
| **Build** | write events to an `outbox` table in the same transaction as the state change; a relay publishes them |
| **Break it** | crash between commit and publish; confirm the event still goes out |
| **Measure** | lost events across 100 induced crashes: N → 0 |
| **Next problem** | events are delivered more than once |
| **Covers** | outbox · dual-write · at-least-once |

### 14.2 — Idempotent consumers and replay

| | |
|---|---|
| **Now** | at-least-once delivery, non-idempotent consumers |
| **Trigger** | a redelivered event double-applies its effect |
| **Diagnose** | replay an event; observe the duplicate |
| **Root cause** | consumers assume exactly-once |
| **Learn** | effectively-once processing, dedup keys, ordering, replay |
| **Build** | event ids + a processed-events table. Replay tooling |
| **Break it** | replay a day of events; state must be unchanged |
| **Measure** | duplicate effects on replay: N → 0 |
| **Next problem** | — |
| **Covers** | idempotent consumers · delivery semantics · replay |

---

# MODULE 15 — Infrastructure and deployment · **CORE**

### 15.1 — Containerisation and configuration

| | |
|---|---|
| **Now** | runs on your laptop |
| **Trigger** | it does not run anywhere else |
| **Diagnose** | try to run it on a clean machine |
| **Root cause** | implicit dependencies and machine-specific config |
| **Learn** | Docker, layer caching, 12-factor config, secret handling, health endpoints |
| **Build** | Dockerfiles for API/worker/agent. Compose for the full stack. Config from environment; secrets never in images |
| **Break it** | run with a missing env var; it should fail loudly at boot, not mysteriously at 3am |
| **Measure** | clean-machine setup time: hours → minutes |
| **Next problem** | deploys are manual and error-prone |
| **Covers** | Docker · 12-factor · secrets · health checks |

### 15.2 — CI/CD

| | |
|---|---|
| **Now** | manual testing and deployment |
| **Trigger** | a regression reaches main; a deploy is forgotten |
| **Diagnose** | count defects that automated checks would have caught |
| **Root cause** | no automated gate |
| **Learn** | pipelines, test pyramid, build artifacts, deployment automation |
| **Build** | CI: lint, types, unit, integration, **and the RAG eval regression gate from 3.3**. CD to a staging environment |
| **Break it** | open a PR that regresses retrieval quality; confirm CI blocks it |
| **Measure** | defects caught pre-merge; deploy time and failure rate |
| **Next problem** | it deploys to staging. Nothing is in the cloud |
| **Covers** | CI/CD · test automation · quality gates |

### 15.3 — Cloud deployment

| | |
|---|---|
| **Now** | containers on a laptop |
| **Trigger** | you need it reachable, durable and observable off your machine |
| **Diagnose** | — |
| **Root cause** | — |
| **Learn** | IaaS vs PaaS, managed services, VPC/networking, IAM, managed Postgres/Redis, object storage, cost |
| **Build** | deploy to **one** cloud (AWS or GCP — pick, do not learn both). Managed Postgres and Redis. Object storage for raw files. Least-privilege IAM |
| **Break it** | terminate an instance; delete a security-group rule; rotate a secret. Recover from each |
| **Measure** | monthly cost; deploy time; recovery time |
| **Next problem** | fixed capacity under variable load |
| **Covers** | cloud · managed services · IAM · networking · cost |

### 15.4 — Autoscaling and operations · **ADV**

| | |
|---|---|
| **Now** | fixed instance counts |
| **Trigger** | overprovisioned at night, saturated at peak |
| **Diagnose** | utilisation over time vs cost |
| **Root cause** | static capacity, variable demand |
| **Learn** | autoscaling signals, scale-to-zero, cold starts, queue-depth-based worker scaling, backup/restore |
| **Build** | scale API on latency/CPU; scale **workers on queue depth** (the correct signal). Backups with a tested restore |
| **Break it** | a traffic spike; a restore drill from backup |
| **Measure** | cost per request; scale-up time; restore time |
| **Next problem** | — |
| **Covers** | autoscaling · operations · backup/restore |

---

# MODULE 16 — Document intelligence · **ADV**

> **Technique catalogue:** `docs/architecture/system-design.md` §8.1–8.2 covers
> extraction and the canonical document model in more detail than this module.

RAG breadth. Deliberately after the platform is solid: each new format is an
ingestion-pipeline change, and you want the measurement harness and reliable
pipeline in place before multiplying input types.

| Stage | Trigger | Build | Covers |
|---|---|---|---|
| **16.1** DOCX/HTML/TXT/MD · **ADV** | users upload non-PDFs and they are rejected | per-format extractors behind one canonical document model | document modelling · parser abstraction |
| **16.2** Scanned PDFs / OCR · **ADV** | a scanned PDF yields zero text; ingestion "succeeds" with nothing indexed | OCR fallback when extracted text is below a threshold per page | OCR · pipeline branching · quality gates |
| **16.3** Tables · **ADV** | questions about tabular data fail; inspection shows tables flattened to unreadable prose | table detection; table-aware chunking that keeps headers with rows | structured extraction · table-aware chunking |
| **16.4** Images and charts · **OPT** | chart questions fail with text-only retrieval | vision model captions figures; captions are indexed; multimodal embeddings if justified | multimodal RAG · vision models |

**Each requires extending the eval set with that format before building it**, or
you cannot tell whether it worked.

---

# MODULE 17 — Advanced RAG · **ADV**

> **Technique catalogue:** `docs/architecture/system-design.md` §8.6 has the full
> eleven-level retrieval ladder with failure modes; §8.9 covers grounding.

| Stage | Trigger | Build | Covers |
|---|---|---|---|
| **17.1** Contextual retrieval · **ADV** | chunks are individually meaningless without their section | prepend an LLM-written situating summary to each chunk before embedding | contextual retrieval · ingestion cost tradeoffs |
| **17.2** Grounding and citation verification · **CORE** | answers cite a real chunk that does not actually support the claim | programmatic check that each cited span supports its claim | grounding · faithfulness |
| **17.3** Abstention · **CORE** | the system confidently answers questions the corpus cannot answer | evidence-sufficiency gate before generation; calibrate against the "impossible" eval questions | abstention · calibration |
| **17.4** Prompt-injection defence · **CORE** | a planted instruction in an uploaded document changes behaviour | the four structural invariants: ACL filtering, untrusted-data delimiting, privilege separation, **no document-controlled tool access** | AI security · structural defence |
| **17.5** Contradiction surfacing · **ADV** | two documents disagree; the system silently picks one and sounds confident | detect conflicting evidence among retrieved chunks; **surface both with provenance and state the conflict** — do not try to resolve which is correct | conflict detection · provenance · honest uncertainty |
| **17.6** Multi-hop / agentic retrieval · **OPT** | questions requiring chained facts fail even with perfect single-shot retrieval | iterative retrieve → reason → retrieve, with a step budget | agentic RAG · iterative retrieval |
| **17.7** Graph retrieval · **OPT** | questions about *relationships* spanning many documents fail regardless of chunk quality ("which suppliers appear in both contracts?") | extract entities and relations into a graph; traverse it alongside vector search | graph RAG · entity extraction · relationship queries |
| **17.8** Multilingual retrieval · **OPT** | the corpus or the questions are not all in one language; cross-language retrieval fails | multilingual embedding model; measure cross-language recall explicitly | multilingual embeddings |
| **17.9** Multi-vector / late interaction · **OPT** | single-vector embeddings lose token-level detail on long chunks | ColBERT-style multi-vector retrieval; measure the index-size cost | late interaction · multi-vector |

**17.2–17.4 are marked CORE** despite living in an advanced module: they are the
difference between a demo and something trustworthy, and they get asked about.

**On contradiction surfacing (17.5):** the scope boundary matters more than the
feature. Surface both sources and state the conflict; **do not attempt to decide
which is correct.** Automatic truth arbitration is a genuinely open research
problem and not this project's job. Knowing where to stop is the lesson.

**17.6–17.9 are OPT and likely to stay unbuilt.** They are on the map so the
territory is complete, and so that when an interviewer asks "how would you handle
relationship queries across documents?" you can answer rather than discover the
gap live.

---

# MODULE 18 — LLMOps · **ADV**

| Stage | Trigger | Build | Covers |
|---|---|---|---|
| **18.1** Prompt versioning · **ADV** | a prompt tweak silently changes quality; nobody can say which version is live | prompts as versioned artifacts; eval run per version; rollback | prompt management · reproducibility |
| **18.2** Online evaluation · **ADV** | offline evals pass; real users are unhappy | thumbs up/down, abstention rate, retrieval-score distributions, sampled human review | online eval · feedback loops |
| **18.3** Cost and model routing · **ADV** | cost per answer is untracked and rising | per-request token/cost accounting; cheap model for easy queries, strong for hard; measure the quality cost | cost engineering · model routing |
| **18.4** Drift detection · **OPT** | quality degrades without a deploy — provider changed the model underneath you | periodic eval on a frozen set; alert on drift | drift · provider risk |

---

# MODULE 19 — Platform and SDK · **ADV**

Phase 2 of your original plan. Entered only when the engine is genuinely reliable.

| Stage | Trigger | Build | Covers |
|---|---|---|---|
| **19.1** Public API design · **CORE** | a second consumer needs the engine and the internal API leaks internals | versioned public API, pagination, consistent errors, OpenAPI | API design · versioning |
| **19.2** SDK · **ADV** | integrators hand-roll HTTP and get it wrong | thin typed clients; retries and pagination handled; examples | SDK design · DX |
| **19.3** Platform hardening · **ADV** | external tenants, real quotas, real support | API keys with scopes, usage metering, per-tenant dashboards, docs | multi-tenancy · metering |

---

# What this project cannot teach you

Study these elsewhere; do not pretend the project covers them.

| Gap | Why | Substitute |
|---|---|---|
| **Genuine high-contention concurrency** | Module 6 helps, but this is not a payments ledger or a ticket sale | build a small seat-booking or wallet service as a side exercise |
| **Consensus (Raft/Paxos)** | you use systems that implement it; you never build one | read the Raft paper; implement a toy leader election |
| **Real operations** | no real users, no on-call, no incident with consequences | chaos drills with a timer; write real postmortems for induced incidents |
| **Cost at scale** | you will never feel a $50k bill shape a decision | do the capacity/cost modelling in 13.4 seriously |
| **Multi-region / geo-distribution** | cannot meaningfully simulate cross-region latency and partitions | read; design on paper; discuss tradeoffs |
| **Database internals** | you use Postgres well; you do not learn its storage engine | separate study: B-trees, MVCC, WAL |
| **Team-scale engineering** | solo project | open-source contribution |
| **Security depth** | basic authn/authz and injection defence only | separate track: OWASP, threat modelling |
| **Kafka / stream processing** | no genuine trigger here | separate project if you need it — do not bolt it on |

---

# The rules that make this work

1. **No stage without an observed trigger.** If you cannot demonstrate the problem in your own running system, you are not ready.
2. **Every stage produces a number.** Before and after. No number, not done.
3. **One variable at a time.** Two changes in one experiment teaches nothing.
4. **Write up the failures too.** The experiment that made things worse is as valuable as the one that helped — and it is what makes you credible in an interview.
5. **"Mastered" means:** implemented it, broke it, debugged it, measured it, and can explain the tradeoff without notes.
6. **Modules 1–10 make you employable.** Everything after is depth. Do not delay applying for jobs until module 19.
