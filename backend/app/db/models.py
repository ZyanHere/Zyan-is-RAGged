"""The backend's tables.

    documents          identity. These bytes were uploaded. They exist.
    ingestion_jobs     attempts. We tried to index them, and here is what
                       happened — once per attempt.
    document_uploads   the bytes themselves, added at 1.3 when the request
                       stopped outliving the work.

Before stage 1.2 the only evidence a document existed was its chunks in
Qdrant — which is a *result*, not a record of intent. A crash midway through
left no trace that anything had been attempted, so "partially indexed" and
"never uploaded" were indistinguishable. These tables are what makes the
difference visible.

── Why identity and attempts are separate tables ────────────────────────────

A single `documents` table with a `status` column would be smaller and would
have worked for two stages. The argument against it was that a retry is a
*second attempt at the same document*, and a status column can only hold the
latest one — so the history of what was tried would be gone exactly when you
need it.

**That argument stopped being theoretical at 2.2.** Re-uploading a file whose
last attempt failed now queues a *new job on the existing document*: no second
identity, no second copy of the bytes, no second embedding bill, and the failed
attempt still on record with its own error and its own `attempts` count. One
document, many jobs — with one table there would have been no way to express
it, and the only options would have been refusing the re-upload or duplicating
the document.

── What identifies a document ───────────────────────────────────────────────

Its bytes. `content_hash` is a SHA-256 with a unique constraint, added at 2.2,
and it is what makes `POST /documents` idempotent. `filename` is a label: two
people can upload different documents both called `report.pdf`, and one person
can upload the same bytes twice under different names.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class IngestionStatus(StrEnum):
    """Where an ingestion attempt is.

        queued  ──▶  processing  ──▶  done
                                 ──▶  failed

    **`queued` arrived at stage 1.3**, and the three original values were
    chosen so that it would be an *addition* rather than a rename — nothing
    existing changed meaning, and no data had to be rewritten.

    The two non-terminal states are not interchangeable, and the difference is
    the whole point of the stage:

        queued      written by the API. Nobody has picked it up.
                    `started_at IS NULL`.
        processing  claimed by a worker, which is now doing the work.
                    `started_at` is when it was claimed.

    That distinction is what makes a backlog measurable
    (`count(*) WHERE status = 'queued'`) and what will let stage 2.1 tell
    "waiting" from "abandoned".

    `StrEnum` rather than `Enum` so the member *is* its string: it compares
    equal to `"processing"`, serialises to JSON without a custom encoder, and
    needs no `.value` at call sites.
    """

    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        """True when nothing further will happen to this job on its own.

        A property rather than a set comparison at each call site, so "is this
        finished?" has one spelling. The client polls until this is true, and
        stage 2.1's reaper will look for the opposite.
        """
        return self in (IngestionStatus.DONE, IngestionStatus.FAILED)


class FailureKind(StrEnum):
    """Whether a failed attempt could ever have succeeded. Stage 2.3.

    Two values, and the line between them is *"would trying again change
    anything?"* — not how serious the failure was, and not whose fault it was.

        permanent   the input is the problem. Retrying runs the same bytes
                    through the same code and gets the same answer.
        transient   the system was the problem. The same bytes would very
                    likely succeed in a minute.

    ── Why this exists, and what it cost not to have it ───────────────────────

    Stage 2.1 retried everything identically, deliberately, so that the waste
    would be observable. Measured on 2026-10-26:

        a corrupt PDF        5 attempts over 14.6s, 4 of them pointless
        a valid document     permanently failed after 22s of downtime,
                             when another minute would have indexed it

    One policy, two opposite failures, tuned for neither. The second is the
    expensive one: `docker compose restart agent` fits inside 22 seconds, and
    the only recovery was a human noticing and re-uploading the file.

    ── Where the classification comes from ───────────────────────────────────

    The agent's HTTP status code, not the engine's exception types. The
    backend never imports `rag` — it learns what happened from the response —
    and that boundary already carries the distinction, because `agent/main.py`
    maps the error hierarchy onto codes. 4xx means *this request can never
    succeed*; 5xx means *the system failed you*. See `_classify` in
    `services/ingestion.py`.

    ── Why not more values ───────────────────────────────────────────────────

    `rate_limited`, `timeout` and `quota_exhausted` are all tempting and all
    the same decision today: wait and try again. Splitting them before any of
    them has been measured separately would be writing a retry policy for
    behaviour nobody has observed, which is what stages 7.1 and 7.2 are for.
    `rag/errors.py` makes the same argument about `EmbeddingError`.
    """

    PERMANENT = "permanent"
    TRANSIENT = "transient"


def new_id() -> uuid.UUID:
    """A time-ordered UUID for a primary key.

    **UUIDv7, not v4.** Both are generated by the application rather than the
    database, which is what this system needs: the backend has to mint an id,
    commit it, and *then* hand it to the agent and on into
    `rag.ingest(document_id=...)` and the Qdrant payload. A `BIGSERIAL` id does
    not exist until after the insert returns.

    The difference between v4 and v7 is index behaviour. A v4 is random, so
    every insert lands on a different B-tree page — the index never stays in
    cache and fragments as it grows. A v7 embeds a millisecond timestamp in its
    high bits, so inserts append to the right-hand edge of the index the way a
    sequence does, while keeping the "generate it anywhere" property.

    It sorts by creation time for free, which is occasionally useful and should
    never be *relied* on: `created_at` is the column that means that.

    `uuid.uuid7()` is new in Python 3.14. Most material still says `uuid4()`.
    """
    return uuid.uuid7()


class Document(Base):
    """A file someone uploaded.

    Identity only. No status, no page counts, no chunk counts — those describe
    an *attempt* and live on `IngestionJob`. The cost of that purity is that
    listing documents with their current state needs a join to the latest job,
    which is a `DISTINCT ON` in Postgres and arrives with the read endpoints.

    The alternative is caching the latest job's status and counts here. Faster
    reads, and two places that can disagree. Worth doing eventually, with a
    measurement rather than a hunch — which is what stage 11.3 is for.
    """

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=new_id
    )

    filename: Mapped[str] = mapped_column(Text, nullable=False)
    """The name as uploaded.

    **Not unique, and never will be.** Two people can legitimately upload
    different documents both called `report.pdf`, and one person can upload the
    same bytes under two names. A name is a label, not an identity.

    `content_hash` below is the identity, from stage 2.2.
    """

    content_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True
    )
    """SHA-256 of the uploaded bytes, hex. **This is what identifies a
    document.** Stage 2.2.

    ── Why the content and not the filename ───────────────────────────────────

    Before this column the same file uploaded twice was two documents, two
    stored blobs and two embedding bills. That is not a hypothetical: every
    document in the database at the time this was added was the same 1244-byte
    PDF, uploaded four times. See `docs/experiments/0002-stage-2-2-baseline-
    audit.md`.

    The hash makes "the same document" a fact about the bytes rather than a
    judgement about a name, which is what lets `POST /documents` be idempotent:
    a browser that retried a timed-out upload now gets the existing document
    back instead of creating a second one.

    ── Why nullable, when every document has bytes ────────────────────────────

    Documents created before stage 1.3 have no `document_uploads` row — the
    bytes were never stored, so they cannot be hashed now. `NOT NULL` would
    require inventing a value for them.

    Postgres treats NULLs as **distinct** in a unique index, so any number of
    un-hashable historical rows coexist with the constraint. That is also the
    correct meaning: we do not know whether two of them were the same file.

    The migration backfills one row per hash group (the oldest) and leaves its
    duplicates NULL, so the duplicates that predate the rule stay visible as
    what they are rather than being deleted to satisfy a constraint invented
    after they were written. The reasoning is in the experiment note above.

    ── Why 64 characters and not Text ─────────────────────────────────────────

    The length is a fact about SHA-256, not a guess about data. Everything else
    in this file is `Text` because its length is genuinely unbounded; this is
    the one column where a width is knowledge rather than a limit.

    ── What changes at stage 5.1 ──────────────────────────────────────────────

    Uniqueness becomes `(tenant_id, content_hash)`. Global uniqueness is right
    with one tenant and **wrong** with two: one tenant uploading a public PDF
    would collide with another's copy of it, and the second would be told it
    already owned a document it has never seen — which is also an information
    leak about what other tenants hold.
    """

    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    """Size of the upload.

    `BigInteger` rather than `Integer`: a 4-byte signed int tops out at 2.1 GB,
    which is a limit nobody expects to meet until a video file arrives. The
    extra four bytes per row are not worth thinking about.
    """

    content_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    """What the browser *claimed* the file was.

    Nullable and untrusted. `rag.extraction` checks the actual PDF magic bytes
    and will happily disagree with this. Stored for diagnostics — a mismatch
    between what was claimed and what was found is interesting.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    """Both are `TIMESTAMPTZ` and both are generated by the database.

    `DateTime(timezone=True)` is the difference between `timestamptz` and
    `timestamp`. The latter stores whatever it was handed with no offset, and
    the bug surfaces months later as a report that is an hour out.

    `server_default=func.now()` makes the *database* clock authoritative. At
    stage 12.1 there are several API instances with independent clocks, and
    "which happened first" needs a single source.

    Note that Postgres's `now()` is `transaction_timestamp()`, not a statement
    clock: a document and its first job, inserted in one transaction, get
    identical timestamps. That is correct — they are one logical event.

    `onupdate` is emitted by SQLAlchemy into the UPDATE statement, so **raw SQL
    bypasses it**. Fine while the ORM is the only writer; the moment something
    else writes — stage 2.1's reaper might — this needs a database trigger.
    """

    upload: Mapped["DocumentUpload | None"] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        lazy="raise",
        # One row, not a list. Without this SQLAlchemy infers a collection
        # from the foreign key and `document.upload` would be `[upload]`.
        uselist=False,
    )
    """The bytes this document was uploaded as. Stage 1.3.

    `| None` in the type because the row can legitimately be absent — nothing
    deletes uploads yet, but something will, and a document whose bytes have
    been reclaimed is still a document.

    Declaring the relationship is what lets `DocumentUpload(document=...)`
    work before the document has an id: SQLAlchemy orders the two INSERTs and
    fills the foreign key in itself. The alternative is flushing the document
    first to get its id, which is a second round trip to avoid one line of
    mapping.

    `lazy="raise"` for the same reason as `jobs`, and it matters more here —
    an accidental lazy load of this attribute pulls the whole file into memory.
    """

    jobs: Mapped[list["IngestionJob"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        lazy="raise",
        order_by="(IngestionJob.queued_at.desc(), IngestionJob.id.desc())",
    )
    """Every attempt at this document, newest first.

    **Ordered by `queued_at`, not `started_at`** — stage 1.3 made `started_at`
    nullable, and a queued job has none. Sorting by a column that is NULL for
    the newest row puts it at an end that depends on the database's NULLS
    default, which is not a thing to rely on.

    The `id` tiebreaker is load-bearing for the same reason it is in
    `list_documents_with_latest_job`: Postgres's `now()` is
    `transaction_timestamp()`, so two jobs written in one transaction share an
    identical `queued_at` and the planner is free to return them in any order.

    `lazy="raise"` is not pedantry. Under async SQLAlchemy, touching an
    unloaded relationship raises `MissingGreenlet` — an error that names
    greenlets, mentions nothing about this attribute, and appears far from the
    query that failed to load it. `lazy="raise"` turns that into an immediate
    "you did not load `jobs`; use `selectinload`".

    It also forces every query to declare what it needs, which is how you avoid
    N+1 before stage 11.3 makes you go and measure one.
    """


class IngestionJob(Base):
    """One attempt to index a document.

    Created and **committed before** `rag.ingest` is called. That ordering is
    the whole of stage 1.2: if this row were written in the same transaction as
    the result, a crash would lose both and the system would be exactly as
    blind as before.
    """

    __tablename__ = "ingestion_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=new_id
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    """`index=True` is doing real work here.

    **Postgres does not automatically index foreign key columns.** It indexes
    the *referenced* side — `documents.id` already has one as the primary key —
    and leaves the referencing side bare. Without this index, `ON DELETE
    CASCADE` sequentially scans this whole table for every document deleted,
    and the "latest job per document" join has no index to use either.

    This is a standard omission and one of the most common causes of a
    mysteriously slow delete.
    """

    status: Mapped[IngestionStatus] = mapped_column(
        Enum(
            IngestionStatus,
            name="ingestion_status",
            # VARCHAR + a CHECK constraint, not a native Postgres ENUM type.
            #
            # A native enum is more compact and type-safe at the database, but
            # it is awkward to change: `ALTER TYPE ... ADD VALUE` cannot be
            # reversed, values cannot be removed without recreating the type,
            # and Alembic's autogenerate cannot see enum changes at all.
            #
            # We *know* `queued` is coming at stage 1.3. A CHECK constraint is
            # dropped and recreated in a migration, which is an ordinary thing
            # to write and an ordinary thing to reverse.
            native_enum=False,
            # The CHECK is declared explicitly in `__table_args__` below
            # instead. `create_constraint=True` would have the *type* emit one
            # too, under the same convention-derived name, and the two collide
            # at CREATE TABLE with "check constraint already exists" — a
            # failure that only appears when the migration runs, not when the
            # model is defined.
            #
            # Turning it off here keeps the type doing what only it can do
            # (converting between `IngestionStatus` and the stored string) and
            # leaves the constraint declared in exactly one place, next to the
            # other three.
            create_constraint=False,
            length=16,
            # Store the member's value ("processing"), not its Python name
            # ("PROCESSING"). Without this the database column holds uppercase
            # strings that no SQL anyone writes by hand will match.
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
    )

    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    """When this attempt was enqueued. Stage 1.3.

    **Why a new column rather than reusing `started_at`.** They are different
    events now. A job is created by the API and picked up by a worker some time
    later — that gap is the queue, and its length is the thing an operator
    wants to see. One column cannot mean both "written down" and "work began"
    without lying about one of them.

    It is also the only creation timestamp this table has: `documents` has
    `created_at`, `ingestion_jobs` never did, and `started_at` had been
    standing in for it.

    `server_default` so the database clock decides, for the same reason as
    everywhere else here — at stage 12.1 there are several API instances with
    independent clocks.
    """

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    """When a worker claimed this job — **nullable since stage 1.3.**

    `NULL` means `queued`: written down, nobody working on it. The
    `started_at_matches_status` constraint below makes that equivalence a
    database guarantee rather than a convention.

    **The `server_default` of `now()` had to be dropped, not merely made
    optional**, and the reason is a SQLAlchemy behaviour worth knowing:
    assigning `None` to a column that has a server default does *not* write
    NULL. SQLAlchemy reads it as "I have no opinion", omits the column from the
    INSERT, and fetches the generated value back in a RETURNING clause. So
    while the default existed, a queued row was not merely inconvenient to
    write — it was **unwritable**, and the first test to try produced a
    constraint violation rather than a NULL.

    The consequence is that every writer now says what it means: the repository
    stamps `func.now()` when it creates a `processing` job, and stage 1.3's
    claim stamps it when a worker takes a `queued` one. Which is the honest
    arrangement anyway — "when did work begin" is not a question the database
    can answer by itself.
    """

    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    """No default, deliberately.

    Set explicitly — as `func.now()`, so the database clock still decides — in
    the same UPDATE that moves `status` out of `processing`. The check
    constraint below requires exactly that, so splitting the two into separate
    statements fails on the first one.
    """

    # ── The lease (stage 2.1) ─────────────────────────────────────────────────
    #
    # Together these are the difference between "a worker owns this" and "a
    # worker owned this at some point and may be dead". Before 2.1 a claim was
    # permanent, so `processing` meant both and could be told apart by nothing.

    lease_token: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True
    )
    """Which *claim* owns this job right now. Minted fresh on every claim.

    **Not a worker id — a claim id.** That distinction is the whole mechanism.
    If it identified the worker, a worker that lost its lease and re-claimed
    the same job later could not tell its two attempts apart. Identifying the
    claim means every completing write can say "the attempt I started", and
    anything else is stale by definition.

    Every write that finishes a job carries `AND lease_token = :mine`, so a
    worker that was reaped affects **zero rows** and finds out. The alternative
    — checking only that *some* live lease exists — is the trap: after a reaper
    requeues and another worker re-claims, the row is `processing` with a fresh
    expiry, so the check passes and the stale worker silently overwrites.

    This is the small version of the fencing-token problem in stage 6.4, where
    the same idea has to work across two datastores. Here one table has
    atomicity, so the conditional UPDATE is the whole implementation.
    """

    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    """When this claim lapses unless the worker renews it.

    **Staying alive is something a worker has to keep doing.** You cannot ask a
    dead process whether it is dead, so the design inverts it: a live worker
    pushes this forward every few seconds, and a dead one stops, which is
    exactly the signal a reaper needs.

    It is a deadline, not a promise. A worker past this time is still running —
    nothing kills it — it has simply lost the right to finish, and the
    conditional write is what enforces that.
    """

    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    """How many times this job has been claimed.

    Incremented by the claim, not by the failure, so it counts *tries* rather
    than *errors* — a worker that died silently still used one up. That is the
    conservative reading and the one that stops a job which crashes its worker
    from cycling forever.

    It is also what stage 2.3 will slice on when it starts classifying failures
    as transient or permanent.
    """

    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    """Not claimable before this moment. `NULL` means claimable now.

    The backoff, expressed as data rather than as a sleep. A worker that slept
    between retries would hold a process doing nothing and would lose the delay
    entirely on restart; a timestamp survives both, and any worker can honour
    it with one extra clause in the claim.

    Set when a failed job is requeued. Deliberately **not** set by the reaper:
    a crashed worker is not a failing job, and recovery should be prompt.
    """

    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Why it failed, in the words the engine used.

    These messages are the point of stage 1.1's fail-loudly design — "this PDF
    is password-protected", "almost certainly a scanned document, nothing was
    indexed" — and this is where they become durable instead of a response body
    nobody kept.

    Set on a **requeued** job too, not only a terminal one: a job waiting to
    retry should still say why it is waiting.
    """

    failure_kind: Mapped[FailureKind | None] = mapped_column(
        Enum(
            FailureKind,
            name="failure_kind",
            native_enum=False,
            create_constraint=False,
            length=16,
            # Store the member's value ("transient"), not its Python name
            # ("TRANSIENT"). Omitting this is a silent trap and it was walked
            # into here: SQLAlchemy's `Enum` persists the *name* by default,
            # so the column held uppercase strings and
            # `ck_ingestion_jobs_failure_kind_allowed` rejected every write.
            # `status` has carried this line since 1.2 for the same reason.
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=True,
    )
    """Whether that error could ever have succeeded on a retry. Stage 2.3.

    Written **whenever `error` is** — which is what
    `ck_ingestion_jobs_failure_kind_matches_error` enforces — and deliberately
    not tied to `status = 'failed'`.

    ── Why it travels with the error and not with the status ──────────────────

    A requeued job carries its last error while it waits, and *why* it is
    waiting is the useful thing to say. "Retrying after a provider outage" and
    "retrying a file that will never parse" look identical without this, and
    only one of them is worth a user's patience.

    Tying the kind to the error also makes the two impossible to drift apart:
    a caller recording a failure has to supply both or violate a constraint.

    ── The same storage decision as `status` ─────────────────────────────────

    `native_enum=False` with `create_constraint=False`: a `VARCHAR` plus an
    explicit CHECK in `__table_args__`, not a Postgres enum type. Adding a
    third kind — if 7.1 ever justifies one — is then an ordinary migration
    that drops and recreates a constraint, inside a transaction. `ALTER TYPE
    … ADD VALUE` on a native enum cannot run in a transaction block at all,
    which is the trap `status` was shaped to avoid at 1.2 and which paid off
    when `queued` arrived at 1.3.
    """

    # ── Results of this attempt ───────────────────────────────────────────────
    #
    # All nullable: they do not exist until the attempt succeeds. A `processing`
    # or `failed` job has nothing to report.

    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pages_with_text: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """The gap between these two is the scanned-PDF signal.

    Ten pages with three yielding text means seven pages are not in the index
    and no question will ever find them. Stage 1.1 surfaces that in the UI;
    storing it here is what makes it answerable later for documents nobody was
    watching at the time.
    """

    characters_extracted: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    document: Mapped["Document"] = relationship(
        back_populates="jobs", lazy="raise"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'processing', 'done', 'failed')",
            name="status_allowed",
        ),
        CheckConstraint(
            "(status IN ('queued', 'processing')) = (finished_at IS NULL)",
            name="finished_at_matches_status",
        ),
        CheckConstraint(
            "(status = 'queued') = (started_at IS NULL)",
            name="started_at_matches_status",
        ),
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="finished_after_started",
        ),
        CheckConstraint(
            "status <> 'failed' OR error IS NOT NULL",
            name="failed_requires_error",
        ),
        CheckConstraint(
            "(status = 'processing') = (lease_token IS NOT NULL)",
            name="lease_matches_status",
        ),
        CheckConstraint(
            "(lease_token IS NULL) = (lease_expires_at IS NULL)",
            name="lease_expiry_matches_token",
        ),
        CheckConstraint(
            "attempts >= 0",
            name="attempts_non_negative",
        ),
        CheckConstraint(
            "failure_kind IS NULL OR failure_kind IN ('permanent', 'transient')",
            name="failure_kind_allowed",
        ),
        CheckConstraint(
            "(error IS NULL) = (failure_kind IS NULL)",
            name="failure_kind_matches_error",
        ),
        Index(
            "ix_ingestion_jobs_expired_leases",
            "lease_expires_at",
            postgresql_where=text("status = 'processing'"),
        ),
    )
    """Ten invariants, enforced by the database rather than by convention.

    **`status_allowed`** — the set of legal states, as a CHECK on a VARCHAR
    rather than a native Postgres enum type. **This is the decision paying
    off:** adding `queued` at stage 1.3 was an ordinary migration that drops
    and recreates this constraint. `ALTER TYPE ... ADD VALUE` on a native enum
    cannot be reversed, so the downgrade would have been impossible to write.

    **`finished_at_matches_status`** — a job is finished exactly when it has a
    finish time. Both sides of the equality are booleans that can never be
    NULL (`status` is NOT NULL, and `IS NULL` always yields true or false), so
    the check is total:

        queued/processing + no finish time   ✅
        queued/processing + a finish time    ❌
        done/failed + no finish time         ❌
        done/failed + a finish time          ✅

    This is what makes "stuck in processing" a structurally visible state —
    which stage 1.2 exists to create and stage 2.1 exists to fix with leases
    and a reaper. Leave it broken for now.

    **`started_at_matches_status`** — the 1.3 addition, and the one that makes
    `queued` mean something enforceable rather than advisory:

        queued + no start time          ✅
        queued + a start time           ❌   "nobody picked it up, and it began"
        processing/done/failed + start  ✅
        processing/done/failed + none   ❌   "it is running, and never started"

    Without it, a bug in the claim could leave a row that is `processing` with
    no record of when — and the first thing stage 2.1's reaper needs is to ask
    "how long has this been running?"

    **`finished_after_started`** — catches clock skew and reversed arguments.
    Still safe with a nullable `started_at`: a row with a `finished_at` is
    `done` or `failed`, which `started_at_matches_status` already requires to
    have a `started_at`. The two constraints lean on each other, so neither
    needs a NULL branch.

    **`failed_requires_error`** — a failure with no explanation is a failure
    you cannot diagnose. If the cause is genuinely unknown the code must store
    `"unknown"`, which is at least honest about it.

    **`lease_matches_status`** — the stage-2.1 addition, and the one that makes
    a lease a guarantee rather than a habit:

        processing + a lease     ✅
        processing + no lease    ❌   "being worked on, by nobody"
        queued/done/failed + a lease  ❌   a lease outliving its work

    The second row is the interesting one. Without this, a bug in the claim
    could produce a `processing` job that no reaper would ever notice, because
    `lease_expires_at < now()` is false for NULL — the job would be invisible
    to the very mechanism built to find it. The constraint makes that
    unrepresentable.

    The third stops the opposite leak: a completed job still holding a lease,
    which would let a stale worker's conditional write succeed against a job
    that finished minutes ago.

    **`lease_expiry_matches_token`** — the two lease columns move together or
    not at all. A token with no expiry never lapses, so nothing reclaims it; an
    expiry with no token has nothing to check ownership against. Either alone
    is a silent hole in the recovery path.

    **`attempts_non_negative`** — cheap, and it catches the decrement nobody
    meant to write.

    Every constraint is named, because the naming convention in `base.py` uses
    `%(constraint_name)s`. An unnamed CheckConstraint raises at table-definition
    time rather than producing an unnameable constraint — the right failure.
    """


class DocumentUpload(Base):
    """The uploaded bytes, kept until something else owns them. Stage 1.3.

    ── Why this table has to exist at all ───────────────────────────────────────

    Until 1.3 the file lived in one place: a `bytes` object inside the request
    that carried it. That was sufficient because the work happened inside that
    same request.

    `202 Accepted` breaks it. The response goes out, the request object is
    collected, and *then* a worker gets around to the job — by which point the
    only copy of the file is gone. So the bytes need a home that outlives the
    request, and it has to be written in the same transaction as the job, or a
    crash between the two produces a job whose input does not exist.

    ── Why a separate table rather than a column on `documents` ────────────────

    Two reasons, one of them a real bug avoided.

    `documents` is the table the list endpoint reads, and it reads it with the
    ORM. A `bytea` column on a mapped class is loaded whenever the entity is
    loaded unless every query remembers to defer it — and the one that forgets
    pulls 25 MB per row into memory to render a sidebar. Postgres TOASTs large
    values out of line, so the *storage* would have been fine; it is the ORM's
    default eagerness that is the hazard.

    It also separates lifetimes. Deleting the bytes while keeping the document
    and its history becomes a `DELETE` from one table rather than an `UPDATE`
    setting a column to NULL, and the FK with `ON DELETE CASCADE` still means
    deleting a document takes its upload with it.

    ── Kept after success, deliberately ────────────────────────────────────────

    Nothing deletes these rows yet, and the storage grows without bound. That
    is a known cost accepted for one reason: stage 2.2 re-indexes documents,
    and a re-index with no stored input is a re-upload. Throwing the bytes away
    on success would make the next stage impossible without one.

    The honest consequence is that the database now grows with the corpus
    rather than with its metadata. **Object storage is the fix** and its
    trigger is named: when the database size becomes a problem, or when stage
    12.1 puts the backend and the worker on different machines. Not before.
    """

    __tablename__ = "document_uploads"

    document_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    """One upload per document, enforced by making the FK the primary key.

    No surrogate id: there is nothing to identify here that `document_id` does
    not already identify, and a second row for the same document would be a
    bug with no meaning. The PK gives the uniqueness and the index that the
    worker's lookup needs, in one declaration.

    Note this is the one foreign key in the schema that does **not** need an
    explicit `index=True` — Postgres does not index FK columns automatically,
    but a primary key is indexed by definition.
    """

    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    """The file, exactly as it arrived.

    `LargeBinary` maps to `bytea`. Not `NULL`-able and not empty: the route
    rejects a zero-byte upload before reaching here, so a row that exists
    always has something to ingest.

    **Stored unvalidated beyond its size.** `rag.extraction` checks the PDF
    magic bytes, and it does so in the worker — so these bytes may well be
    something that will fail to parse. That is correct: the job records the
    attempt, and the failure belongs on the job rather than at the door.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    """When the bytes were stored.

    Not the same question as `documents.created_at`, even though today they
    are written in one transaction and will hold identical values. They answer
    different things once anything ever re-uploads, and this is the column a
    future cleanup job would sort by.
    """

    document: Mapped["Document"] = relationship(
        back_populates="upload", lazy="raise"
    )
    """The document these bytes belong to.

    Adds no column — the foreign key above is the whole storage story. What it
    adds is the ability to construct the pair in one go, before either row has
    been flushed, which is why `create_document_with_job` can write document,
    job and upload in a single transaction without an intermediate round trip.
    """
