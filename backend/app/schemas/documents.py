"""HTTP shapes for the backend's document endpoints.

── One model for all three endpoints ────────────────────────────────────────

`POST /documents`, `GET /documents` and `GET /documents/{id}` all answer the
same question — *what is the state of this document?* — so they return the same
shape. Two models that must be kept in sync are two chances to drift, and the
drift shows up as a frontend that renders one endpoint correctly and the other
not quite.

They diverge at stage 1.3, when POST starts returning `202 Accepted` and a job
id instead of a result. That is a real difference in meaning and will earn its
own model; identical fields today do not.

── Why the backend has its own shape at all ─────────────────────────────────

Until stage 1.2 the backend forwarded the agent's response body verbatim. From
here it builds its own from the database, because the database is what knows
what happened — the agent's reply is only the news that arrived.

The field names are deliberately the ones the frontend already reads, so the
move changed the *source* of the response without changing its shape.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.db.models import Document, IngestionJob, IngestionStatus


class DocumentRead(BaseModel):
    """A document and the state of its most recent ingestion attempt.

    Numbers rather than a success boolean, because the dangerous outcome at
    this stage is not a crash — it is a scanned PDF that indexes nothing and
    reports success. The gap between `page_count` and `pages_with_text` is the
    tell, and it is durable now rather than a response body nobody kept.
    """

    document_id: UUID
    filename: str
    created_at: datetime

    status: IngestionStatus | None = None
    """`processing`, `done`, `failed` — or `None`.

    `None` means the document exists with no ingestion attempt recorded at all.
    That should be impossible: the two rows are written in one transaction.

    It is representable anyway, because the query behind the list uses an outer
    join. Hiding such a row with an inner join would conceal exactly the kind
    of inconsistency this stage exists to make visible — and a stage about
    seeing previously invisible states should not start by filtering one out.
    """

    page_count: int | None = None
    pages_with_text: int | None = None
    characters_extracted: int | None = None
    chunk_count: int | None = None
    """All optional: they do not exist unless the attempt succeeded."""

    error: str | None = None
    """The engine's own words, on failure.

    These are what stage 1.1's fail-loudly design produced — "is not a PDF. It
    starts with b'just som'", "almost certainly a scanned document". The
    response carried them before; now they survive the request that produced
    them.
    """

    attempts: int = 0
    """How many times this document has been claimed for ingestion.

    Exposed at stage 2.1 because without it the client cannot tell two very
    different situations apart — they are both `status: "queued"`:

        attempts = 0   nobody has tried this yet
        attempts = 2   it has failed twice and is waiting to try again

    A user watching the first one should be patient. A user watching the second
    one is watching something go wrong repeatedly, and showing them an
    identical badge would be hiding it.

    Defaults to `0` rather than `None`: a document with no job at all has
    genuinely been attempted zero times, so there is no missing-value case to
    represent.
    """

    next_attempt_at: datetime | None = None
    """When a waiting job becomes claimable again. `None` means "now".

    This is the backoff, which lives in the row rather than in a worker's
    sleep. Exposing it lets the client count down — and because the list is
    already polled every two seconds while anything is unfinished, the
    countdown is live for free, with no timer in the UI.
    """

    finished_at: datetime | None = None
    """`None` while an attempt is still running.

    Guaranteed to mean exactly that by
    `ck_ingestion_jobs_finished_at_matches_status`, which forbids a terminal
    job without a finish time and a running one with one. So a `processing` row
    with no `finished_at` is unambiguously *started, never finished* — the
    state stage 2.1's reaper will go looking for.
    """

    @classmethod
    def from_rows(
        cls, document: Document, job: IngestionJob | None
    ) -> "DocumentRead":
        """Build the response from what is actually in the database.

        Reading back from the rows rather than echoing what we just sent means
        the response cannot claim something the database does not hold. A write
        that silently failed to apply becomes visible here instead of being
        papered over by the values still in memory.
        """
        return cls(
            document_id=document.id,
            filename=document.filename,
            created_at=document.created_at,
            status=job.status if job else None,
            page_count=job.page_count if job else None,
            pages_with_text=job.pages_with_text if job else None,
            characters_extracted=job.characters_extracted if job else None,
            chunk_count=job.chunk_count if job else None,
            error=job.error if job else None,
            attempts=job.attempts if job else 0,
            next_attempt_at=job.next_attempt_at if job else None,
            finished_at=job.finished_at if job else None,
        )


class DocumentListResponse(BaseModel):
    """An envelope, not a bare array.

    `{"items": [...]}` rather than `[...]`, and the asymmetry is the whole
    argument: adding `total` or `next_cursor` to an envelope is backward
    compatible, while wrapping a bare array later breaks every client that
    already iterates it.

    The cost is one level of unwrapping, paid once in the frontend's
    `transformResponse`.
    """

    items: list[DocumentRead]


MAX_PAGE_SIZE = 200
"""An upper bound on `limit`, enforced server-side.

Not a guess about what clients want — a guard against one of them asking for
everything. A client-supplied limit with no ceiling is a request to build an
arbitrarily large response in memory, which is a denial of service with a
polite query string.

Pagination proper is deliberately absent. Offset pagination is the obvious next
step and it is wrong in a way that is easy to miss: with rows arriving while a
client reads pages, `OFFSET` silently skips and repeats records. Keyset
pagination is the correct answer, and the `ORDER BY created_at DESC, id DESC`
already in the repository is precisely the key it needs.

The trigger is the list outgrowing a single response — or stage 19.1, where the
API becomes a published surface and pagination stops being optional.
"""

DEFAULT_PAGE_SIZE = 50


class DocumentListQuery(BaseModel):
    """Query parameters for the list endpoint."""

    limit: int = Field(default=DEFAULT_PAGE_SIZE, gt=0, le=MAX_PAGE_SIZE)
