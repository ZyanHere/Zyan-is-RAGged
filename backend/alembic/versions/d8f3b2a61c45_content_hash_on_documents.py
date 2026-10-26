"""Content hash on documents

Revision ID: d8f3b2a61c45
Revises: c7e2a4d81b30
Create Date: 2026-10-26

Stage 2.2 — a document stops being identified by when it arrived.

── What this makes possible ──────────────────────────────────────────────────

`POST /documents` can be idempotent. Until now the same bytes uploaded twice
were two documents, two blobs and two embedding bills, because nothing in the
schema could say they were the same thing. A browser retrying a timed-out
upload did exactly that.

SHA-256 of the uploaded bytes, unique, is the smallest thing that makes "the
same document" a fact rather than a judgement about a filename.

── Hand-written, for one reason the others did not have ──────────────────────

The order of the three steps below is load-bearing, and autogenerate would
produce the first and the third with nothing in between:

    1. add the column
    2. backfill it
    3. create the unique constraint

Reversed — constraint before backfill — the backfill fails on the first pair of
duplicates. The migration has to decide what the existing rows *mean* before
asserting a rule about them, which is the same shape as the lease backfill in
`c7e2a4d81b30` and is the part a generator cannot do.

── The backfill, and why it does not hash everything ─────────────────────────

Measured before writing this (`docs/experiments/0002-stage-2-2-baseline-
audit.md`): **every document in the database was the same 1244-byte PDF**,
uploaded four times. Hashing all of them and then adding the constraint would
fail on every row but one.

Three options, and the reason for the choice:

  delete the duplicates
      Clean table, and it destroys data to satisfy a constraint invented after
      that data was written. Those rows were created under a rule the system
      genuinely had — *every upload is a document*. It would also delete the
      only live specimen of the duplicate-chunk corruption this stage exists
      to fix.

  backfill nothing, leave every historical row NULL
      Non-destructive, and dedupe then applies to no pre-2.2 document: a fifth
      upload of those bytes would create a fifth document.

  backfill the oldest row per hash group  ← this one
      The canonical row gets the hash; its duplicates keep NULL. The next
      upload of that file dedupes correctly, and nothing is destroyed.

The cost, stated rather than hidden: those duplicates are permanently exempt
from the uniqueness rule. A future reader will find rows the constraint should
have prevented, and this paragraph is the explanation.

── Why the database computes the hash ────────────────────────────────────────

`sha256(bytea)` is built in from Postgres 11 (we run 17), and
`encode(sha256(content), 'hex')` produces byte-for-byte what
`hashlib.sha256(content).hexdigest()` produces in the upload route. So the
backfill and the live path cannot disagree about what the hash of a file is —
and no blob has to be pulled across the wire into a Python loop to find out.

── Downgrade ────────────────────────────────────────────────────────────────

Fully reversible and loses nothing that cannot be recomputed: the column is
derived from `document_uploads.content`, which this migration does not touch.
Re-running `upgrade()` reconstructs it exactly.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d8f3b2a61c45"
down_revision: Union[str, Sequence[str], None] = "c7e2a4d81b30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The final name, not a bare one. Unlike the `ck` pattern, the `uq` pattern in
# `app/db/base.py` is `uq_%(table_name)s_%(column_0_name)s` — it has no slot
# for a caller-supplied name, so there is no double-prefix hazard here and the
# expanded name is what both this file and autogenerate will compute.
UNIQUE_HASH = "uq_documents_content_hash"


def upgrade() -> None:
    """Add the column, backfill the canonical rows, then assert uniqueness."""

    # ── 1. The column ────────────────────────────────────────────────────────
    #
    # Nullable, and it stays nullable. See the model's docstring: documents
    # from before stage 1.3 have no stored bytes to hash.
    op.add_column(
        "documents",
        sa.Column("content_hash", sa.String(length=64), nullable=True),
    )

    # ── 2. One row per distinct hash: the oldest ─────────────────────────────
    #
    # `DISTINCT ON (hash) ... ORDER BY hash, created_at, id` is the same "first
    # row per group" idiom the repository uses for latest-job-per-document, run
    # the other way round. `id` is the tiebreaker because `created_at` is
    # `transaction_timestamp()` and is identical for rows written together.
    #
    # Documents with no `document_uploads` row are not touched by the join and
    # keep NULL, which is the whole reason the column is nullable.
    op.execute(
        """
        UPDATE documents d
           SET content_hash = canonical.hash
          FROM (
            SELECT DISTINCT ON (encode(sha256(u.content), 'hex'))
                   u.document_id,
                   encode(sha256(u.content), 'hex') AS hash
              FROM document_uploads u
              JOIN documents dd ON dd.id = u.document_id
             ORDER BY encode(sha256(u.content), 'hex'), dd.created_at, dd.id
          ) AS canonical
         WHERE d.id = canonical.document_id
        """
    )

    # ── 3. The constraint ────────────────────────────────────────────────────
    #
    # After the backfill, so it is checked against data that already satisfies
    # it. If this still fails, the message names the colliding rows and the
    # transaction rolls back whole — DDL in Postgres is transactional, so a
    # failure here leaves no half-added column behind.
    op.create_unique_constraint(UNIQUE_HASH, "documents", ["content_hash"])


def downgrade() -> None:
    """Drop the constraint and the column. Nothing is lost — see the docstring."""
    op.drop_constraint(UNIQUE_HASH, "documents", type_="unique")
    op.drop_column("documents", "content_hash")
