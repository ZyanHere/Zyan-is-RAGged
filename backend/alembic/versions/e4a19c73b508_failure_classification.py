"""Failure classification

Revision ID: e4a19c73b508
Revises: d8f3b2a61c45
Create Date: 2026-10-26

Stage 2.3 — a failure stops being one undifferentiated thing.

── What this makes possible ──────────────────────────────────────────────────

Until now every failure was retried identically, which stage 2.1 did on purpose
so the waste would be observable. It was, on 2026-10-26, and in both directions:

    a corrupt PDF      5 attempts over 14.6s — 4 of them could never succeed
    a valid document   permanently failed after 22s of downtime, when another
                       minute would have indexed it

The second is the expensive one. `docker compose restart agent` fits inside 22
seconds, and the only recovery was a human noticing and re-uploading the file.

`failure_kind` is what lets one policy become two: stop immediately when the
input is the problem, and keep trying for minutes when the system is.

── Why the constraint is tied to `error` and not to `status` ─────────────────

`(error IS NULL) = (failure_kind IS NULL)`.

A requeued job carries its last error while it waits, so the kind has to be
allowed on a non-terminal row — and *why* a job is waiting is the useful thing
to say. "Retrying after a provider outage" and "retrying a file that will never
parse" are indistinguishable without it, and only one deserves patience.

Tying them together also makes them unable to drift: a caller recording a
failure supplies both or violates a constraint.

── The backfill guesses, and that is the right call exactly once ─────────────

Rows written before this column have an error and no kind, so the constraint
would reject every one of them. There are three possible responses:

  make the column's constraint weaker   the invariant stops being an invariant
                                        for all future rows, to accommodate a
                                        handful of old ones

  delete the old rows                   destroys the two specimens this stage's
                                        trigger consists of

  infer the kind from the message       fragile, and only has to work once  ←

Matching on message text is exactly the kind of thing that should never appear
in running code — it breaks the moment a wording changes, silently. In a
migration it runs once, against rows that already exist and whose text is
already known, and is then never executed again. The `CASE` below is written
against the two messages actually on record.

Anything it cannot recognise becomes `transient`, which is the safe direction:
the worst outcome is an operator retrying something that was never going to
work, rather than the system refusing to retry something that would have.

── Downgrade ────────────────────────────────────────────────────────────────

Reversible and lossy in one direction worth naming: dropping the column loses
the distinction, so every historical failure becomes "it failed" again and the
record of which ones were worth retrying is gone. Nothing can reconstruct it
except the same string matching.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e4a19c73b508"
down_revision: Union[str, Sequence[str], None] = "d8f3b2a61c45"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Bare names. `op.create_check_constraint` runs what it is given through the
# metadata naming convention, so passing an already-expanded name produces
# `ck_ingestion_jobs_ck_ingestion_jobs_…`. A lesson from the 1.3 migration.
KIND_ALLOWED = "failure_kind_allowed"
KIND_MATCHES_ERROR = "failure_kind_matches_error"


def upgrade() -> None:
    """Add the column, classify what is already there, then assert the rule."""

    # ── 1. The column ────────────────────────────────────────────────────────
    #
    # `VARCHAR(16)` with an explicit CHECK rather than a native Postgres enum,
    # matching `status`. Adding a third kind later is then an ordinary
    # migration inside a transaction; `ALTER TYPE … ADD VALUE` cannot run in a
    # transaction block at all.
    op.add_column(
        "ingestion_jobs",
        sa.Column("failure_kind", sa.String(length=16), nullable=True),
    )

    # ── 2. Classify the rows that predate the column ─────────────────────────
    #
    # See the module docstring: string matching, once, against messages that
    # already exist. The two on record are a corrupt PDF ("is not a valid
    # PDF: Stream has ended unexpectedly") and an unreachable agent ("Could
    # not reach the agent at …").
    #
    # The two permanent patterns are the engine's own wordings, from
    # `InvalidDocumentError` and `NoTextExtractedError` in `rag/errors.py`.
    # Everything else falls through to `transient`, which errs towards
    # retrying rather than towards refusing to.
    op.execute(
        """
        UPDATE ingestion_jobs
           SET failure_kind = CASE
                 WHEN error LIKE '%is not a valid PDF%'
                   OR error LIKE '%no extractable text%'
                   OR error LIKE '%no usable chunks%'
                   OR error LIKE '%is empty (0 bytes)%'
                 THEN 'permanent'
                 ELSE 'transient'
               END
         WHERE error IS NOT NULL
           AND failure_kind IS NULL
        """
    )

    # ── 3. The invariants ────────────────────────────────────────────────────
    #
    # After the backfill, so they are checked against data that already
    # satisfies them. DDL in Postgres is transactional, so a failure here
    # rolls back the column and the backfill together rather than leaving the
    # table half-migrated.
    op.create_check_constraint(
        KIND_ALLOWED,
        "ingestion_jobs",
        "failure_kind IS NULL OR failure_kind IN ('permanent', 'transient')",
    )
    op.create_check_constraint(
        KIND_MATCHES_ERROR,
        "ingestion_jobs",
        "(error IS NULL) = (failure_kind IS NULL)",
    )


def downgrade() -> None:
    """Reverse it. Loses the classification — see the module docstring."""
    op.drop_constraint(KIND_MATCHES_ERROR, "ingestion_jobs", type_="check")
    op.drop_constraint(KIND_ALLOWED, "ingestion_jobs", type_="check")
    op.drop_column("ingestion_jobs", "failure_kind")
