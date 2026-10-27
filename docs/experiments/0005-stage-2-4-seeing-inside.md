# 0005 — Stage 2.4: seeing inside

**Date:** 2026-10-27
**Stage:** 2.4 (Seeing inside)
**Status:** complete. All figures `[measured]` unless marked.

## The trigger was half stale, and the accurate half is sharper

The Evolution Map said:

> *"every `logger.info` in this codebase is currently discarded"* `[measured]`

True when written. **Stage 1.3 fixed half of it** — `worker.py` called
`logging.basicConfig(level=INFO)`, with a comment saying it was "a floor, not a
design… stage 2.4 replaces this line". Counted before starting:

| process | app `logger.info` lines observed |
|---|---|
| worker | **31** |
| API (uvicorn) | **0** |

**The worker could be watched; the API could not.** uvicorn configures its own
loggers and never touches the root, so `logging.lastResort` took every record
and dropped anything below WARNING.

The expensive part is *which* lines those were:

```text
main.py          "database pool ready" / "database pool disposed"
ingestion.py     every accept, every dedupe decision, every retry request,
                 every lost race
```

**The entire dedupe and replay story from stages 2.2 and 2.3 logged at INFO in
the API process**, so a duplicate upload, a lost race and an operator clicking
Retry were all invisible — in the one process a user talks to.

This is the third consecutive stage whose Problem row needed correcting against
the system as it actually was. The pattern is now worth stating as a rule: **a
Problem row is a hypothesis with a date on it, and the stage immediately before
it is the most likely thing to have changed its truth.**

## Measures

| Measure | Before | After |
|---|---|---|
| app log lines reaching a handler in the API process | **0** | **all of them** |
| answering "is ingestion healthy?" | 3 queries, schema knowledge, container access | **1 request, 18 ms** |
| tracing one upload across both processes | impossible — no shared id | **one `grep`** |
| diagnosing an induced failure from logs alone | impossible | **the whole incident** |

### Logs reaching a handler: 0 → all

Two uploads of the same bytes through the running API:

```text
INFO app.main: database pool ready
INFO app.services.ingestion: ingestion queued document_id=01a17c3a-… job_id=…
INFO app.services.ingestion: duplicate upload of filename=log-probe.pdf
                             matched document_id=01a17c3a-… (status=done)
```

That third line has existed since stage 2.2 and **had never once been seen.**

### One id, two processes

```text
the caller was told: 4a35ad25ca61

  API     INFO  app.services.ingestion   ingestion queued document_id=01a17cfc-…
  WORKER  INFO  __main__                 claimed job_id=… document_id=…
  WORKER  INFO  httpx                    HTTP Request: POST localhost:8001 200 OK
  WORKER  INFO  app.services.ingestion   ingestion done job_id=…
```

The `httpx` line is the one to notice. The filter sits on the **handler**, not
on a logger, so a third-party library that knows nothing about request ids is
correlated for free. A `LoggerAdapter` would have covered only the lines we
remembered to decorate — and the line you need in an incident is reliably the
one nobody decorated.

### An induced failure, from logs alone

Agent stopped, one upload, no database access:

```text
INFO    ingestion queued document_id=01a17cfd-…
INFO    claimed job_id=… document_id=…
WARNING ingestion failed … kind=transient attempt=1 of 15; retrying in …
INFO    claimed job_id=…                        (×4 more)
WARNING ingestion failed … attempt=5 of 15
```

All five attempts share the id, which is right: the request that created the
job caused every attempt at it.

### The health question

```text
BEFORE   3 separate psql queries          0.93 s wall, and that is not the cost
AFTER    GET /stats                       0.018 s
```

**The wall-clock number is the least interesting part.** The real "before" was
that someone had to know the schema, have access to the container, and write
three queries — which **see three different instants**, so a job counted
`queued` by the first and `processing` by the second made the totals disagree
with each other in a way that reads as a counting bug rather than as a job
doing its work.

`/stats` is one statement, so it is one snapshot. That property is asserted by
a test counting SQL through a SQLAlchemy event listener, because "it looks like
one query" stops being true the first time someone adds a field.

### The queue indicator, where depth is not enough

Worker stopped, two documents uploaded, `queued_at` backdated nine minutes:

```text
stats:  claimable=2  oldest_age_seconds=540  in_flight=0
header: "2 queued · stalled"   (amber)
```

Worker restarted: `claimable=0, oldest=None, done=17`, and the badge vanishes.

**Depth alone cannot distinguish a busy system from a stopped one.** 300 jobs
draining steadily is healthy; 3 that have not moved in an hour is an outage,
and depth reports the first as worse. `oldest_queued_age` is the number that
separates them, and the stalled condition needs all three signals — queued
work, nothing in flight, and time having passed. Any two of them describe a
normal busy system.

## The decisions, and what they cost

### The metrics are read, not counted

The roadmap asked for "counters for jobs by state, a histogram for job
duration, a gauge for queue depth". All three were already durable facts,
because **stage 1.3 made the queue a table**.

A counter would be a cached, partial copy — and *partial* settles it. A counter
lives in one process; run two workers and each has its own, so a queue-depth
gauge summed across them counts the same rows twice. The only correct source
for a fact about the queue is the queue.

What is genuinely not in the database, and so needs instrumenting when
something aggregates: API request rate and duration per endpoint, and
agent-call latency separately from total job duration. Both are stage 10.1.

**Prometheus exposition is deferred to 10.1**, where something scrapes. 10.1's
own entry says the problem it solves is "metrics exist but are not aggregated",
so a wire format now would have no consumer — and a format nobody reads drifts
from the thing it describes. The SQL written here is what its collector calls,
so none of it is thrown away.

### The classification of scope: 2.5 exists now

As written, 2.4 was logging + request_id + metrics + the fake embedder + a
capacity probe + three deferred 1.3 measurements — roughly double any previous
stage. The observability half shipped here; the rest became **2.5**, with its
own trigger: *you cannot run a load experiment without a provider you can
drive.*

Keeping them apart also keeps this stage's measure clean. "An induced failure
is diagnosable from logs alone" is a different claim from "p95 under 20
concurrent uploads", and entangling them would have meant neither was finished
until both were.

## Four findings about testing, all found by mutation

**1. The headline test was compromised by the exact trap it documented.**

`test_an_info_line_reaches_a_handler` was written specifically to avoid
`caplog`, with a docstring explaining that pytest attaches its own root handler
and that any assertion against it would pass against the broken configuration.

Then it walked the logger hierarchy, found **pytest's** handler, and passed —
with the original bug reintroduced (`"handlers": []` on root).

The fix asks a narrower question: is one of *our* handlers on the path?
`RequestIdFilter` is the marker, since nothing else installs it. Re-mutated:

| mutation | tests failed |
|---|---|
| no handler on root *(the original bug)* | 10 (was 8) |
| root level WARNING | 6 |
| filter removed from the handler | 5 |

**Reading did not find this; mutation did.** Writing a warning about a trap is
not the same as avoiding it.

**2. A claim with no test at all.**

Emptying `expose_headers` survived every test. CORS hides all but a safelist of
response headers, so without it JavaScript reading `X-Request-ID` gets `null` —
no error, no console warning, server looks correct. The most characteristically
silent failure in a stage about silent failures, and the only claim here that
had no test.

**3. The security claim was overstated, and checking corrected it.**

The docstring said the inbound-header regex stops a newline forging log
entries. Tested with a raw socket: h11 parses
`X-Request-ID: evil\r\nX-Injected: yes` as **two headers**, so the application
sees `evil`. CRLF never reaches us over HTTP/1.1.

What the regex uniquely buys is **length and charset** — verified live, a
200-character inbound id is replaced with a generated one. It still refuses
newlines, because a guard should not depend on which parser sits in front of
it, but claiming CRLF is what it is *for* overstated it.

**4. A `NamedTuple` refused to be built incomplete.**

The claim's `RETURNING` fetched `request_id` and the `ClaimedJob(...)`
construction did not pass it on. Eight worker tests failed with a `TypeError`
naming the missing argument, rather than silently carrying `None` — the same
property that made adding `failure_kind` safe at 2.3.

## Known gaps, stated rather than left implicit

**The frontend still has no tests.** `PipelineStatus` ships with none, and its
stalled threshold — three conditions and a 60-second bound — is exactly the
kind of logic that rots silently. This debt has been outstanding since 1.3 and
this is the third stage to add client behaviour on top of it. It is getting
more expensive, not less.

**Pure unit tests now require Postgres.** `conftest.py`'s session-scoped autouse
fixture builds the test database for every test, including `test_logging.py`
and `test_failure_classification.py`, which touch no database at all. Its
docstring still claims "Every test here talks to Postgres", which stopped being
true this stage.

**The environmental flake persists.** Roughly one backend run in six errors on
an unrelated test with a connection `TimeoutError` and passes on a rerun —
investigated at 2.3 and not data pollution. The host also slept four times
during this stage's work, taking Docker with it each time.

## Test counts

224 backend (was 179), 44 rag, `tsc` and `eslint` clean.
