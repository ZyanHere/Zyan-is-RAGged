"""Leases, attempts and backoff

Revision ID: c7e2a4d81b30
Revises: b1c4e7a90f22
Create Date: 2026-10-25

Stage 2.1 — a claim stops being permanent.

── What this makes possible ──────────────────────────────────────────────────

Before these columns, `status = 'processing'` meant two things that could not
be told apart: *a worker is on this* and *a worker died holding this three days
ago*. One row, two meanings, no way to choose.

A lease separates them by making survival something a worker has to keep
doing. `lease_expires_at` moves forward only while someone is alive to move it;
when nobody is, it lapses on its own and a reaper can see that.

`lease_token` answers the second question, which is subtler: *which* claim owns
the job. Identifying the claim rather than the worker is what lets a completing
write say "the attempt I started" — so a worker that was reaped and whose job
was re-claimed affects zero rows instead of silently overwriting someone else's
result.

── Hand-written, for three reasons ───────────────────────────────────────────

1. **Autogenerate cannot see inside a CHECK constraint.** It compares tables,
   columns, indexes and foreign keys; the three new invariants below are
   invisible to it. A generated migration would have produced the columns and
   silently omitted every guarantee that makes them trustworthy.

2. **`attempts NOT NULL` needs a backfill that tells the truth.** Defaulting
   existing rows to 0 would claim nothing had ever been tried, which is false
   for every row with a `started_at` — including the stranded job this stage
   exists to recover. See the `CASE` below.

3. **The partial index is a deliberate choice**, not something autogenerate
   would infer.

── The index, and why it is partial ──────────────────────────────────────────

The reaper runs on every worker loop and asks the same question each time:

    WHERE status = 'processing' AND lease_expires_at < now()

A plain index on `lease_expires_at` would cover every job that ever ran,
forever — and all but a handful of those rows are `done`, where the column is
NULL and the question never applies. A partial index indexes only the rows that
can match, so it stays roughly the size of the number of jobs in flight rather
than the size of the table's whole history.

This is the one index in the schema added *before* `EXPLAIN ANALYZE` justified
it, and the reason is scheduling rather than performance: the query runs on a
timer in every worker, so it is the one read whose cost grows with nothing but
age. Stage 11.3 should still check it earns its keep.

── Downgrade ────────────────────────────────────────────────────────────────

Reversible, and **lossy in one direction worth naming**: dropping `attempts`
destroys the retry history, so a job that had failed four times looks identical
to one that has never been tried. Jobs mid-lease are left `processing` with no
lease — which is precisely the stuck state stage 2.1 exists to remove, and the
honest thing for the old schema to say.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7e2a4d81b30"
down_revision: Union[str, Sequence[str], None] = "b1c4e7a90f22"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Bare names. `op.create_check_constraint` and `op.drop_constraint` both run
# what they are given through the metadata's naming convention — passing the
# already-expanded name produces `ck_ingestion_jobs_ck_ingestion_jobs_…` and
# fails with "constraint does not exist". A lesson from the previous migration.
LEASE_MATCHES = "lease_matches_status"
LEASE_EXPIRY = "lease_expiry_matches_token"
ATTEMPTS_NON_NEGATIVE = "attempts_non_negative"

REAPER_INDEX = "ix_ingestion_jobs_expired_leases"


def upgrade() -> None:
    """Add the lease, the attempt counter and the backoff timestamp."""

    # ── 1. The lease: two columns that are both NULL or both set ─────────────
    op.add_column(
        "ingestion_jobs",
        sa.Column("lease_token", sa.UUID(), nullable=True),
    )
    op.add_column(
        "ingestion_jobs",
        sa.Column(
            "lease_expires_at", sa.DateTime(timezone=True), nullable=True
        ),
    )

    # ── 2. attempts, in three steps because rows already exist ───────────────
    op.add_column(
        "ingestion_jobs",
        sa.Column("attempts", sa.Integer(), nullable=True),
    )
    # A row that has a `started_at` was claimed at least once. Saying 0 would
    # be a lie, and the stranded row from stage 1.3 is exactly such a row.
    op.execute(
        """
        UPDATE ingestion_jobs
           SET attempts = CASE WHEN started_at IS NULL THEN 0 ELSE 1 END
         WHERE attempts IS NULL
        """
    )
    op.alter_column(
        "ingestion_jobs",
        "attempts",
        existing_type=sa.Integer(),
        nullable=False,
        server_default=sa.text("0"),
    )

    # ── 3. The backoff ───────────────────────────────────────────────────────
    #
    # NULL means claimable now, which is what every existing row should be —
    # no default needed and none wanted. A default of `now()` would have made
    # every historical row look like it was waiting to retry.
    op.add_column(
        "ingestion_jobs",
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── 4. Give pre-existing `processing` rows an already-expired lease ──────
    #
    # **This step was discovered by the migration failing, and it is the most
    # interesting thing in the file.**
    #
    # `lease_matches_status` says a `processing` job holds a lease. Every row
    # written before this migration is `processing` with no lease — not because
    # of a bug, but because the concept did not exist when they were written.
    # Adding the constraint without this UPDATE fails with "violated by some
    # row", which is the ordinary shape of adding an invariant to a live table:
    # you have to decide what the old rows *meant* and say it in the new
    # vocabulary.
    #
    # What they meant is "a worker claimed this and never came back". In the
    # new vocabulary that is exactly **a lease that has expired** — so the
    # backfill writes one, dated at the moment work began and therefore already
    # long past.
    #
    # The consequence is the good part: the first worker to run its reaper
    # finds these rows and requeues them. The migration does not perform the
    # recovery itself — it hands the stranded jobs to the machinery built to
    # recover them, which is how stage 2.1's own trigger closes itself.
    op.execute(
        """
        UPDATE ingestion_jobs
           SET lease_token = gen_random_uuid(),
               lease_expires_at = COALESCE(started_at, now())
         WHERE status = 'processing'
           AND lease_token IS NULL
        """
    )

    # ── 5. The invariants ────────────────────────────────────────────────────
    #
    # Added after both backfills, so they are checked against data that already
    # satisfies them rather than failing halfway through the migration.
    op.create_check_constraint(
        LEASE_MATCHES,
        "ingestion_jobs",
        "(status = 'processing') = (lease_token IS NOT NULL)",
    )
    op.create_check_constraint(
        LEASE_EXPIRY,
        "ingestion_jobs",
        "(lease_token IS NULL) = (lease_expires_at IS NULL)",
    )
    op.create_check_constraint(
        ATTEMPTS_NON_NEGATIVE,
        "ingestion_jobs",
        "attempts >= 0",
    )

    # ── 6. The reaper's index ────────────────────────────────────────────────
    op.create_index(
        REAPER_INDEX,
        "ingestion_jobs",
        ["lease_expires_at"],
        postgresql_where=sa.text("status = 'processing'"),
    )


def downgrade() -> None:
    """Reverse it. Loses the retry history — see the module docstring."""
    op.drop_index(REAPER_INDEX, table_name="ingestion_jobs")

    op.drop_constraint(ATTEMPTS_NON_NEGATIVE, "ingestion_jobs", type_="check")
    op.drop_constraint(LEASE_EXPIRY, "ingestion_jobs", type_="check")
    op.drop_constraint(LEASE_MATCHES, "ingestion_jobs", type_="check")

    op.drop_column("ingestion_jobs", "next_attempt_at")
    op.drop_column("ingestion_jobs", "attempts")
    op.drop_column("ingestion_jobs", "lease_expires_at")
    op.drop_column("ingestion_jobs", "lease_token")
