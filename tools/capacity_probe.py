"""What does concurrency do to this system? Stage 2.5.

Three questions have been deferred since stage 1.3, all for the same reason:
none of them can be answered against a paid, rate-limited provider. A real
ingest under load is rejected with a 429 in about a second, so every result
would be a quota artefact rather than an observation about concurrency.

With `EMBEDDING_PROVIDER=fake` the embedder becomes a dial, and the questions
become answerable:

    1. upload p50/p95 under concurrent load — sync and async
    2. does `/health` degrade while the system is saturated?
    3. where is the knee?

── The two latencies, which the roadmap conflates ──────────────────────────────

    response    how long the caller waits. The whole point of stage 1.3.
    completion  upload until the document is `done`. Essentially unchanged by
                1.3, because the work still has to happen.

Reporting one number would make 1.3 look either miraculous or pointless,
depending which you picked. Against the synchronous target they are the same
number by construction, and that *is* the finding.

── Why the "before" is a port and not a git checkout ───────────────────────────

`POST :8001/documents` on the agent is still synchronous — a `def` handler
calling `rag.ingest` inline — kept deliberately so an agent problem can be told
from a backend one. It is the code path 1.1 and 1.2 used.

**Stated rather than hidden:** it skips the backend hop and the Postgres
writes, so it measures synchronous *ingestion*, not the whole 1.2 system.
Embedding dominates, so the shape holds; the absolute sync numbers are a lower
bound on what 1.2 would have shown.

── Running it ──────────────────────────────────────────────────────────────────

    # the probe's own ceiling, first — see --self-test
    python tools/capacity_probe.py --self-test

    python tools/capacity_probe.py --target sync  --n 10 --n 40 --n 60
    python tools/capacity_probe.py --target async --n 10 --n 40 --n 60

The agent must be running with the fake provider and a non-default collection;
it refuses to start otherwise. The backend and a worker are needed for
`--target async`.
"""

import argparse
import asyncio
import statistics
import sys
import time
import uuid
from dataclasses import dataclass, field

import httpx

sys.path.insert(0, "rag")
from tests.fixtures.pdf_builder import build_pdf  # noqa: E402

AGENT = "http://localhost:8001"
BACKEND = "http://localhost:8000"

# Long enough that a saturated system does not look like a failure. The probe
# is measuring queueing; a timeout here would record a zero where the true answer
# is "slow".
TIMEOUT = 300.0

# A tick gap longer than this means the host stalled — it slept, or something
# else took the CPU. Stage 2.3 learned to report that rather than fold it into
# the numbers.
STALL_SECONDS = 10.0


def percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile. No interpolation, no numpy.

    With N in the tens, interpolating between two samples implies a precision
    the sample size does not support. Nearest-rank returns a number that was
    actually observed, which is the honest thing to report.
    """
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = min(int(fraction * len(ordered)), len(ordered) - 1)
    return ordered[index]


@dataclass
class Outcome:
    """One upload's result. Three states, never two.

    `error` is not a slow success. Stage 2.3's measurement script reported
    "GAVE UP" when its own watch loop timed out, and the database said the
    document was still running — so this records what happened rather than
    what the probe concluded.
    """

    response_seconds: float | None = None
    completion_seconds: float | None = None
    status_code: int | None = None
    error: str | None = None


@dataclass
class HealthWatch:
    """`/health` latency, sampled throughout the run on its own connection.

    Its own connection, because the question is whether a saturated ingest
    path starves an unrelated endpoint — and sharing a pool with the uploads
    would make the probe the cause of its own answer.
    """

    latencies: list[float] = field(default_factory=list)
    failures: int = 0
    stalls: list[float] = field(default_factory=list)


def document(index: int) -> bytes:
    """A small, valid PDF, unique per upload.

    Unique because stage 2.2 deduplicates by content hash: identical bytes
    would make every upload after the first a no-op `200`, and the probe would
    measure the dedupe path instead of the ingest path.
    """
    marker = uuid.uuid4().hex[:8]
    return build_pdf([[f"Capacity probe {index}. Marker {marker}."]])


async def watch_health(
    client: httpx.AsyncClient, url: str, watch: HealthWatch, stop: asyncio.Event
) -> None:
    last = time.perf_counter()
    while not stop.is_set():
        now = time.perf_counter()
        if now - last > STALL_SECONDS:
            watch.stalls.append(now - last)
        last = now

        start = time.perf_counter()
        try:
            response = await client.get(f"{url}/health")
            if response.status_code != 200:
                watch.failures += 1
            else:
                watch.latencies.append(time.perf_counter() - start)
        except Exception:
            watch.failures += 1

        await asyncio.sleep(0.2)


async def upload_sync(client: httpx.AsyncClient, index: int) -> Outcome:
    """The agent's blocking endpoint. Response *is* completion."""
    start = time.perf_counter()
    try:
        response = await client.post(
            f"{AGENT}/documents",
            files={"file": (f"probe-{index}.pdf", document(index), "application/pdf")},
        )
    except Exception as exc:
        return Outcome(error=f"{type(exc).__name__}: {exc}")

    elapsed = time.perf_counter() - start
    return Outcome(
        response_seconds=elapsed,
        # Identical by construction, and that is the finding rather than a
        # shortcut: a synchronous endpoint cannot separate them.
        completion_seconds=elapsed,
        status_code=response.status_code,
    )


async def upload_async(client: httpx.AsyncClient, index: int) -> Outcome:
    """The backend's `202`, then poll until the worker finishes it."""
    start = time.perf_counter()
    try:
        response = await client.post(
            f"{BACKEND}/documents",
            files={"file": (f"probe-{index}.pdf", document(index), "application/pdf")},
        )
    except Exception as exc:
        return Outcome(error=f"{type(exc).__name__}: {exc}")

    outcome = Outcome(
        response_seconds=time.perf_counter() - start,
        status_code=response.status_code,
    )
    if response.status_code not in (200, 202):
        outcome.error = f"unexpected {response.status_code}"
        return outcome

    document_id = response.json()["document_id"]
    deadline = time.perf_counter() + TIMEOUT

    while time.perf_counter() < deadline:
        try:
            state = (await client.get(f"{BACKEND}/documents/{document_id}")).json()
        except Exception as exc:
            outcome.error = f"polling failed: {type(exc).__name__}"
            return outcome

        if state["status"] == "done":
            outcome.completion_seconds = time.perf_counter() - start
            return outcome
        if state["status"] == "failed":
            outcome.error = f"ingestion failed: {state['error'][:60]}"
            return outcome

        await asyncio.sleep(0.25)

    # Not a failure of the system — a failure to observe it. Said plainly.
    outcome.error = f"still running after {TIMEOUT:.0f}s (INCONCLUSIVE)"
    return outcome


async def run(target: str, n: int) -> None:
    uploader = upload_sync if target == "sync" else upload_async
    watched = AGENT if target == "sync" else BACKEND

    stop = asyncio.Event()
    watch = HealthWatch()

    # `limits` raised above N so the probe's own pool is not the bottleneck.
    # Default is 10 keep-alive connections, which at N=60 would serialise the
    # uploads and the probe would measure itself.
    limits = httpx.Limits(max_connections=n + 20, max_keepalive_connections=n + 20)

    async with (
        httpx.AsyncClient(timeout=TIMEOUT, limits=limits) as uploads,
        httpx.AsyncClient(timeout=10.0) as health,
    ):
        watcher = asyncio.create_task(watch_health(health, watched, watch, stop))

        started = time.perf_counter()
        outcomes = await asyncio.gather(*(uploader(uploads, i) for i in range(n)))
        wall = time.perf_counter() - started

        stop.set()
        await watcher

    report(target, n, outcomes, watch, wall)


def report(
    target: str, n: int, outcomes: list[Outcome], watch: HealthWatch, wall: float
) -> None:
    ok = [o for o in outcomes if o.error is None]
    errors = [o for o in outcomes if o.error is not None]

    responses = [o.response_seconds for o in ok if o.response_seconds is not None]
    completions = [o.completion_seconds for o in ok if o.completion_seconds is not None]

    print(f"\n── {target.upper()}  N={n} ───────────────────────────────────")
    print(f"  wall clock        {wall:.2f}s   throughput {len(ok) / wall:.1f}/s")
    print(f"  completed         {len(ok)}/{n}")

    if errors:
        print(f"  !! {len(errors)} did not complete:")
        for kind in sorted({o.error.split(":")[0] for o in errors if o.error}):
            count = sum(1 for o in errors if o.error and o.error.startswith(kind))
            print(f"       {count:>3} x {kind}")

    if responses:
        print(
            f"  response          p50 {percentile(responses, 0.5):6.3f}s   "
            f"p95 {percentile(responses, 0.95):6.3f}s   "
            f"max {max(responses):6.3f}s"
        )
    if completions:
        print(
            f"  completion        p50 {percentile(completions, 0.5):6.3f}s   "
            f"p95 {percentile(completions, 0.95):6.3f}s   "
            f"max {max(completions):6.3f}s"
        )

    if watch.latencies:
        print(
            f"  /health           p50 {percentile(watch.latencies, 0.5):6.3f}s   "
            f"p95 {percentile(watch.latencies, 0.95):6.3f}s   "
            f"max {max(watch.latencies):6.3f}s   "
            f"({len(watch.latencies)} samples, {watch.failures} failed)"
        )
    if watch.stalls:
        print(f"  !! host stalled {len(watch.stalls)}x — timings are unreliable")


async def self_test(n: int) -> None:
    """The probe's own ceiling, before trusting anything it says about the system.

    A load generator that saturates before its target does is measuring
    itself. `/health` is the cheapest endpoint in the system — it touches no
    database and no disk — so N concurrent calls to it bound what this script
    can possibly drive.

    If the ceiling here is near the throughput measured against uploads, the
    upload numbers are about the probe.
    """
    print(f"\n── SELF-TEST  N={n} concurrent /health ─────────────────────")

    limits = httpx.Limits(max_connections=n + 20, max_keepalive_connections=n + 20)
    async with httpx.AsyncClient(timeout=30.0, limits=limits) as client:

        async def ping() -> float:
            start = time.perf_counter()
            await client.get(f"{BACKEND}/health")
            return time.perf_counter() - start

        started = time.perf_counter()
        latencies = await asyncio.gather(*(ping() for _ in range(n)))
        wall = time.perf_counter() - started

    print(f"  wall clock        {wall:.3f}s   ceiling {n / wall:.0f} req/s")
    print(
        f"  latency           p50 {percentile(list(latencies), 0.5):6.4f}s   "
        f"p95 {percentile(list(latencies), 0.95):6.4f}s"
    )
    print("  -> upload throughput anywhere near this ceiling is a measure of")
    print("     the probe, not of the system.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target", choices=("sync", "async"))
    parser.add_argument(
        "--n",
        type=int,
        action="append",
        default=None,
        help="concurrency; repeatable to sweep. Go past 40 — the agent's "
        "threadpool bound and the predicted knee.",
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    levels = args.n or [10, 40, 60]

    if args.self_test:
        asyncio.run(self_test(max(levels)))
        return

    if not args.target:
        parser.error("--target is required unless --self-test is given")

    for n in levels:
        asyncio.run(run(args.target, n))


if __name__ == "__main__":
    main()
