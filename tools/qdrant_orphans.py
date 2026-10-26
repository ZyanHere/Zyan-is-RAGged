"""Reconcile the vector store against the database. Stage 2.2.

`ON DELETE CASCADE` stops at the edge of Postgres. Deleting a document removes
its job and its stored bytes and leaves its vectors exactly where they were —
so the collection accumulates points belonging to documents that no longer
exist, and `search()` keeps ranking against them.

That is not a tidiness problem. It is a wrong answer: the baseline audit was
followed by a live query whose first citation pointed at
`01a12abc-9048-7215-935c-3e37d6958385`, a document `GET /documents/{id}` answers
404 for. Three quarters of the collection was in that state.

── What this reports ──────────────────────────────────────────────────────────

Five groups, because "orphan" is only one of the ways the two stores disagree
and the others need different answers:

    agreed      in both, counts match                       nothing to do
    orphan      in Qdrant, not in Postgres                  deletable here
    mismatch    in both, counts differ                      re-ingest it
    missing     Postgres says N chunks, Qdrant has none      re-ingest it
    pending     in Postgres, never successfully ingested     expected, ignore

Only **orphan** is ever deleted. A mismatch is repaired by re-ingesting the
document, which stage 2.2 made safe and which keeps the text; deleting it would
throw away a working document to satisfy a count. `missing` is the same
dual-write failure in the other direction and deserves to be seen rather than
silently fixed.

── How to run it ──────────────────────────────────────────────────────────────

Two steps, and both constraints behind that are real.

**Qdrant is embedded**, a library inside the agent container holding an
exclusive lock on the `myrag_agent_qdrant_data` volume. No host process and no
second process in that container can open it while the agent runs. So this runs
in a one-shot container from the agent image, with the agent stopped.

**The agent must not learn about Postgres.** The dependency direction is
deliberate and `tools/check_dependencies.py` exists to keep it — so the live
document list arrives as *data*, exported on the host, rather than by giving
this script a database driver.

    # 1. export the live documents (no ceiling, see the warning below)
    docker compose exec -T postgres psql -U myrag -d myrag -t -A -F',' -c \\
      "SELECT d.id, COALESCE(j.chunk_count::text, '') FROM documents d \\
         LEFT JOIN LATERAL (SELECT chunk_count FROM ingestion_jobs \\
           WHERE document_id = d.id AND status = 'done' \\
           ORDER BY queued_at DESC, id DESC LIMIT 1) j ON true" > live.csv

    # 2. audit (read-only)
    docker compose stop agent
    MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps \\
      -v "$PWD/live.csv:/tmp/live.csv:ro" -v "$PWD/tools:/tools:ro" \\
      --entrypoint python agent /tools/qdrant_orphans.py /tmp/live.csv
    docker compose start agent

    # 3. and again with --delete once the report looks right

`MSYS_NO_PATHCONV=1` is required on Windows: Git Bash rewrites `/tmp/live.csv`
into a Windows path and the container then looks for
`/app/agent/C:/Program Files/Git/tmp/live.csv`.

── Why SQL and not the backend's own API ──────────────────────────────────────

The plan for this stage said to read the live list from `GET /documents`, which
is the tidier dependency. It is also a hazard here: that endpoint caps `limit`
at `MAX_PAGE_SIZE` (200), and **a truncated live list makes live documents look
like orphans.** This script deletes orphans. The failure mode is deleting the
vectors of documents that are perfectly fine, and it gets worse as the system
grows — invisible until there are 201 documents.

Keyset pagination would fix it and is deliberately absent until it is needed
(see `schemas/documents.py`). Until then a direct `SELECT` with no ceiling is
the safer input for a destructive tool, and it needs no backend process running
either. The guards below exist for the same reason.
"""

import argparse
import pathlib
import sys

sys.path.insert(0, "/app/rag")

import rag


def load_live(path: pathlib.Path) -> dict[str, int | None]:
    """`document_id -> expected chunk count`, or None if never ingested.

    An empty second field means no `done` job: the document exists but has
    never been successfully indexed. Qdrant holding nothing for it is correct,
    and holding something for it is a mismatch worth seeing.
    """
    live: dict[str, int | None] = {}

    for number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = line.strip()
        if not line:
            continue
        parts = line.split(",")
        if len(parts) != 2:
            raise SystemExit(
                f"{path}:{number}: expected 'id,chunk_count', got {line!r}. "
                f"Refusing to act on a list it cannot read — see the module "
                f"docstring for the exact psql command."
            )
        document_id, raw_count = parts[0].strip(), parts[1].strip()
        live[document_id] = int(raw_count) if raw_count else None

    return live


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "live_csv",
        type=pathlib.Path,
        help="'id,chunk_count' per line, exported from Postgres on the host",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="actually remove orphaned points (default: report only)",
    )
    args = parser.parse_args()

    live = load_live(args.live_csv)
    stored = rag.document_chunk_counts()

    # ── Guard: an empty live list means every document looks orphaned ────────
    #
    # The export is a shell pipeline on the host and can fail quietly — a
    # container that was not running, a typo in the database name, a
    # redirection that produced an empty file. The result is a file that reads
    # as "Postgres contains nothing", and acting on it would delete the entire
    # collection.
    #
    # Refusing is correct even though an empty database is technically
    # possible: in that case there is nothing worth this tool's risk, and the
    # collection can be dropped deliberately instead.
    if not live:
        print(
            f"REFUSING: {args.live_csv} lists no documents. Either the export "
            f"failed or the database is empty; both are reasons not to delete "
            f"anything. Nothing was changed."
        )
        return 2

    groups: dict[str, list[tuple[str, str]]] = {
        "agreed": [],
        "orphan": [],
        "mismatch": [],
        "missing": [],
        "pending": [],
    }

    for document_id, points in sorted(stored.items()):
        if document_id not in live:
            groups["orphan"].append((document_id, f"{points} points"))
            continue
        expected = live[document_id]
        if expected is None:
            groups["pending"].append(
                (document_id, f"{points} points, no successful ingestion")
            )
        elif expected == points:
            groups["agreed"].append((document_id, f"{points} points"))
        else:
            groups["mismatch"].append(
                (document_id, f"{points} points, Postgres says {expected}")
            )

    for document_id, expected in sorted(live.items()):
        if expected and document_id not in stored:
            groups["missing"].append(
                (document_id, f"no points, Postgres says {expected}")
            )
        elif expected is None and document_id not in stored:
            # The ordinary state of a queued or failed document. Not reported:
            # a list of everything that is fine is noise in a report whose job
            # is to surface what is not.
            pass

    total_points = sum(stored.values())
    orphan_points = sum(
        int(detail.split()[0]) for _, detail in groups["orphan"]
    )

    print(f"Postgres: {len(live)} documents")
    print(f"Qdrant:   {len(stored)} documents, {total_points} points")
    print()

    for name in ("orphan", "mismatch", "missing", "pending", "agreed"):
        rows = groups[name]
        print(f"{name.upper():10} {len(rows)}")
        for document_id, detail in rows:
            print(f"           {document_id}  {detail}")
    print()

    if not groups["orphan"]:
        print("No orphans. The two stores agree about which documents exist.")
        return 0

    share = orphan_points / total_points if total_points else 0
    print(
        f"{orphan_points} of {total_points} points ({share:.0%}) belong to "
        f"documents that do not exist."
    )

    if not args.delete:
        print("Read-only run. Pass --delete to remove them.")
        return 0

    for document_id, _ in groups["orphan"]:
        # `keep_ids=[]` means "keep nothing", so this removes every point of
        # the document. The pipeline's own replacement path calls the same
        # function with the ids it just wrote — one way to delete, used two
        # ways, so there is no second deletion path to keep correct.
        rag.delete_chunks_except(document_id, keep_ids=[])
        print(f"deleted {document_id}")

    remaining = rag.document_chunk_counts()
    still_orphaned = [d for d in remaining if d not in live]

    print()
    print(f"after: {len(remaining)} documents, {sum(remaining.values())} points")
    print(f"MEASURE orphaned points: {orphan_points} -> "
          f"{sum(remaining[d] for d in still_orphaned)}")

    # The report is only as good as the delete. Verifying by re-reading the
    # store rather than trusting the loop means a delete that silently matched
    # nothing is a failure here instead of a surprise at the next audit.
    return 0 if not still_orphaned else 1


if __name__ == "__main__":
    raise SystemExit(main())
