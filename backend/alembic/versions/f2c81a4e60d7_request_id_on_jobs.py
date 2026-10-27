"""Request id on jobs

Revision ID: f2c81a4e60d7
Revises: e4a19c73b508
Create Date: 2026-10-27

Stage 2.4 — one id that both processes can see.

── What this makes possible ──────────────────────────────────────────────────

Following one upload across the process boundary. The API accepts a document
and returns; a worker picks it up some time later, possibly after a restart,
possibly on another machine. Until now nothing connected the two sides: the
API's log lines and the worker's shared only a `document_id`, which is a fact
about the *document* rather than about the request that asked for it.

A retry makes the difference concrete. One document, five attempts, five
different reasons — and `document_id` cannot tell you which request caused the
third one.

── Why the queue being a table is what allows this ───────────────────────────

There is no other channel from the API to the worker. No message body, no
header, no shared memory. Stage 1.3 made the queue a Postgres table, and that
decision is what lets a value travel between the two processes at all: the API
writes it on the row, the worker's `UPDATE … RETURNING` claim reads it back.

With a broker the id would ride in the message. Here it rides in the row.

── Nullable, with no backfill, deliberately ──────────────────────────────────

Every job written before this migration genuinely has no request to attribute
it to. The stage 2.3 migration inferred `failure_kind` from message text,
because the alternative was weakening a constraint for every future row; there
is no constraint here and nothing to infer from, so the honest value is NULL.

A generated placeholder would be worse than the gap: it would look like a real
request id, and someone would eventually search the logs for it and find
nothing, with no way to tell whether the lines were missing or the id was
invented.

── Why `VARCHAR(64)` and not `TEXT` ──────────────────────────────────────────

The value can come from an inbound `X-Request-ID` header, which is
attacker-controlled. The middleware validates it, but a bound in the schema is
the backstop that keeps an unvalidated path from ever writing a megabyte into
a column that is printed on every log line for that job.

── Downgrade ────────────────────────────────────────────────────────────────

Reversible and lossy in the obvious way: dropping the column loses the
correlation for every job that has one. Nothing can reconstruct it, because
the id only ever existed in the request that created the row.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2c81a4e60d7"
down_revision: Union[str, Sequence[str], None] = "e4a19c73b508"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """One nullable column. No constraint, no backfill, no index.

    **No index, and that is a decision rather than an omission.** The query
    this column serves — "show me everything for request X" — runs against a
    *log aggregator*, not against Postgres. Looking a job up by request id in
    SQL is a thing a human does once while debugging, on a table with
    thousands of rows, where a sequential scan is instant.

    Stage 11.3's rule is indexes justified by `EXPLAIN ANALYZE`. The one index
    added ahead of that rule — 2.1's partial index for the reaper — was
    justified by *scheduling*: it runs on a timer in every worker. Nothing
    runs this one on a timer.
    """
    op.add_column(
        "ingestion_jobs",
        sa.Column("request_id", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    """Drop it. See the module docstring on what that loses."""
    op.drop_column("ingestion_jobs", "request_id")
