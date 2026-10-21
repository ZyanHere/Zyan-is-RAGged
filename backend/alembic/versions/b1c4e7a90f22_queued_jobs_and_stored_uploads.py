"""Queued jobs and stored uploads

Revision ID: b1c4e7a90f22
Revises: 00d59e7cc79b
Create Date: 2026-10-19

Stage 1.3 — ingestion moves out of the request cycle.

── Why this migration is hand-written ────────────────────────────────────────

`alembic revision --autogenerate` produces almost none of it, for three
separate reasons worth knowing before you trust autogenerate again:

1. **It cannot see inside a CHECK constraint.** Autogenerate compares tables,
   columns, indexes and foreign keys. The *text* of a CHECK is opaque to it, so
   adding `'queued'` to `status_allowed` is invisible — it would report no
   change at all and the new status would be rejected at runtime by a
   constraint nobody noticed was stale.

2. **Existing rows need a backfill.** `queued_at` is `NOT NULL`, and this
   database has real rows. Adding the column `NOT NULL` in one step fails;
   adding it nullable, filling it, then tightening it is three steps that
   autogenerate has no way to infer.

3. **The order matters.** The old `finished_at_matches_status` is false for
   nothing yet, but the new `started_at_matches_status` would be violated by
   any future `queued` row with a start time. Constraints have to be swapped
   before any code can write the new state, and in a sequence where the table
   is never momentarily invalid.

── The ordering, and why each step is where it is ───────────────────────────

    add queued_at NULLABLE          cannot be NOT NULL while rows exist
    backfill from started_at        every existing job had already started
    SET NOT NULL                    now true for every row
    started_at DROP NOT NULL        a queued job has no start time
    swap the two CHECK constraints  drop-then-create; a CHECK cannot be altered
    add started_at_matches_status
    create document_uploads         independent of all of the above

── The backfill is lossy in one direction, and that is correct ──────────────

`queued_at = started_at` for existing rows. Those jobs were created in the
synchronous era, where "written down" and "work began" happened in the same
transaction microseconds apart — so the value is not merely a sensible guess,
it is what the two columns would have held had `queued_at` existed. Nothing is
being invented.

── The downgrade loses information, and says so ─────────────────────────────

A `queued` row has no equivalent in the old schema: `started_at` was `NOT NULL`
and `'queued'` was not a legal status. The downgrade therefore maps such rows
to `processing` with `started_at = queued_at`, which is the closest honest
statement the old schema can make — "an attempt that began and has not
finished". It is a lossy conversion and running it will misreport a backlog as
work in progress.

`document_uploads` is dropped outright, which **destroys the stored bytes**. A
downgrade after this point loses the ability to re-ingest anything without a
re-upload.

Verified both ways: `upgrade → downgrade → upgrade` round-trips, and
autogenerate reports no drift afterwards.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1c4e7a90f22"
down_revision: Union[str, Sequence[str], None] = "00d59e7cc79b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# **Bare names, not the full database names.**
#
# `op.drop_constraint` runs the name it is given through the metadata's naming
# convention, exactly as `op.create_check_constraint` does — so both take the
# short name and `ck_%(table_name)s_%(constraint_name)s` from `db/base.py`
# expands it.
#
# Passing the already-expanded name is a mistake that costs one migration run:
# it produces `ck_ingestion_jobs_ck_ingestion_jobs_status_allowed` and fails
# with "constraint does not exist". Worth knowing that Postgres's transactional
# DDL meant that failure left the schema completely untouched — no half-applied
# migration to unpick, which is not true of MySQL.
STATUS_ALLOWED = "status_allowed"
FINISHED_MATCHES = "finished_at_matches_status"
STARTED_MATCHES = "started_at_matches_status"


def upgrade() -> None:
    """Add `queued`, a queue timestamp, and somewhere for the bytes to live."""

    # ── 1. queued_at, in three steps because rows already exist ──────────────
    op.add_column(
        "ingestion_jobs",
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE ingestion_jobs SET queued_at = started_at WHERE queued_at IS NULL"
    )
    op.alter_column(
        "ingestion_jobs",
        "queued_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )

    # ── 2. started_at becomes nullable, and loses its default ────────────────
    #
    # **Both halves are required, and the second is not obvious.** Making the
    # column nullable is not enough to let a queued row exist, because
    # SQLAlchemy reads `started_at=None` on a column with a server default as
    # "no opinion": it omits the column from the INSERT and lets the default
    # fill it in. With `now()` still attached, a queued job is unwritable — the
    # row comes back with a start time and violates
    # `started_at_matches_status`.
    #
    # Dropping the default makes every writer state its intent, which is
    # correct: "when did work begin" is a fact about a worker claiming a job,
    # not something the database can infer from an INSERT.
    op.alter_column(
        "ingestion_jobs",
        "started_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
        server_default=None,
        existing_server_default=sa.text("now()"),
    )

    # ── 3. The status vocabulary, and what each state implies ────────────────
    #
    # Dropped and recreated rather than altered: Postgres has no
    # `ALTER CONSTRAINT` for a CHECK's expression. This is the whole reason
    # stage 1.2 chose VARCHAR + CHECK over a native enum — `ALTER TYPE ... ADD
    # VALUE` cannot be reversed, so a downgrade would have been unwritable.
    op.drop_constraint(STATUS_ALLOWED, "ingestion_jobs", type_="check")
    op.create_check_constraint(
        "status_allowed",
        "ingestion_jobs",
        "status IN ('queued', 'processing', 'done', 'failed')",
    )

    op.drop_constraint(FINISHED_MATCHES, "ingestion_jobs", type_="check")
    op.create_check_constraint(
        "finished_at_matches_status",
        "ingestion_jobs",
        "(status IN ('queued', 'processing')) = (finished_at IS NULL)",
    )

    op.create_check_constraint(
        "started_at_matches_status",
        "ingestion_jobs",
        "(status = 'queued') = (started_at IS NULL)",
    )

    # ── 4. The uploaded bytes ────────────────────────────────────────────────
    #
    # A separate table, not a column on `documents`: the list endpoint loads
    # `Document` entities with the ORM, and a `bytea` column there is pulled
    # into memory by any query that forgets to defer it.
    op.create_table(
        "document_uploads",
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_uploads_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "document_id", name=op.f("pk_document_uploads")
        ),
    )


def downgrade() -> None:
    """Reverse it. **Lossy** — see the module docstring.

    Queued jobs become `processing`, and every stored upload is destroyed.
    """
    op.drop_table("document_uploads")

    # Queued rows cannot exist in the old schema. Convert before tightening
    # anything, or the NOT NULL below fails on exactly those rows.
    op.execute(
        """
        UPDATE ingestion_jobs
           SET started_at = queued_at,
               status = 'processing'
         WHERE status = 'queued'
        """
    )

    op.drop_constraint(STARTED_MATCHES, "ingestion_jobs", type_="check")

    op.drop_constraint(FINISHED_MATCHES, "ingestion_jobs", type_="check")
    op.create_check_constraint(
        "finished_at_matches_status",
        "ingestion_jobs",
        "(status = 'processing') = (finished_at IS NULL)",
    )

    op.drop_constraint(STATUS_ALLOWED, "ingestion_jobs", type_="check")
    op.create_check_constraint(
        "status_allowed",
        "ingestion_jobs",
        "status IN ('processing', 'done', 'failed')",
    )

    # Restore both the NOT NULL and the default the old schema had. Safe
    # because the UPDATE above left no NULL `started_at` behind.
    op.alter_column(
        "ingestion_jobs",
        "started_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )
    op.drop_column("ingestion_jobs", "queued_at")
