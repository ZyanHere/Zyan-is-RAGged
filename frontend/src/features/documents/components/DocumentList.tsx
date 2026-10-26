"use client";

import { useDocuments } from "@/features/documents/useDocuments";
import { cn } from "@/lib/utils";
import { useRetryDocumentMutation } from "@/services/documentsApi";
import type { DocumentRecord } from "@/types";

/**
 * Every document the server has, with the state of its last ingestion attempt.
 *
 * ── This is where results arrive now ───────────────────────────────────────
 *
 * Until stage 1.3 the upload response carried the outcome and this list was a
 * second place to see it. The response is now a `202` receipt, so this is the
 * *only* place a user learns what happened — page counts, chunk counts, the
 * scanned-PDF warning and failures all land here.
 *
 * It reads `useDocuments` rather than the query directly, so that the decision
 * about when to poll is made once. `EmptyState` uses the same hook; RTK Query
 * gives them one cache entry and one request between them.
 *
 * ── Why calling the query in two places is cheap ───────────────────────────
 *
 * RTK Query caches by endpoint and argument, so both components subscribe to
 * one cache entry and one fetch. Components ask for what they need, and the
 * library works out that it is the same thing. With polling it goes further:
 * the interval is shared too, so the other component does not have to know
 * polling is happening.
 */
export function DocumentList() {
  const { documents, isLoading, isError, errorMessage, isAnythingPending } =
    useDocuments();

  if (isLoading) {
    return (
      <p className="px-1 py-2 text-xs text-neutral-400">Loading documents…</p>
    );
  }

  if (isError) {
    return (
      <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs leading-relaxed text-red-700">
        {errorMessage ?? "Could not load documents."}
      </p>
    );
  }

  if (documents.length === 0) {
    return (
      <p className="px-1 py-2 text-xs leading-relaxed text-neutral-400">
        No documents indexed yet.
      </p>
    );
  }

  return (
    <div>
      <p className="mb-1.5 flex items-center gap-1.5 px-1 text-xs font-medium uppercase tracking-wide text-neutral-400">
        Indexed · {documents.length}
        {/* The only indication that polling is running. Without it a queue
            that is not draining looks identical to a UI that has frozen. */}
        {isAnythingPending && (
          <span
            className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-400"
            title="Checking for updates"
            aria-label="Checking for updates"
          />
        )}
      </p>
      <ul className="flex flex-col gap-1">
        {documents.map((document) => (
          <DocumentRow key={document.documentId} document={document} />
        ))}
      </ul>
    </div>
  );
}

function DocumentRow({ document }: { document: DocumentRecord }) {
  const pagesLost =
    document.pageCount !== null && document.pagesWithText !== null
      ? document.pageCount - document.pagesWithText
      : 0;

  return (
    <li className="rounded-lg border border-neutral-200 bg-white px-3 py-2">
      <div className="flex items-start gap-2">
        <p
          className="min-w-0 flex-1 truncate text-sm text-neutral-700"
          title={document.filename}
        >
          {document.filename}
        </p>
        <StatusBadge status={document.status} />
      </div>

      {/* The numbers moved here from the upload panel at stage 1.3, because
          this is where they now arrive. `charactersExtracted` is included: it
          is the only place a user can see that a document extracted almost
          nothing, which is the quiet failure. */}
      {document.status === "done" && (
        <p className="mt-0.5 text-xs tabular-nums text-neutral-400">
          {document.pageCount} pages · {document.chunkCount} chunks
          {document.charactersExtracted !== null && (
            <> · {document.charactersExtracted.toLocaleString()} chars</>
          )}
          {pagesLost > 0 && (
            <span className="text-amber-600">
              {" · "}
              {pagesLost} empty
            </span>
          )}
        </p>
      )}

      {/* The policy decision the type deliberately does not encode: any gap at
          all is worth flagging, because those pages are not in the index and
          no question will ever find them. */}
      {document.status === "done" && pagesLost > 0 && (
        <p className="mt-1 rounded border border-amber-200 bg-amber-50 px-2 py-1.5 text-xs leading-relaxed text-amber-800">
          {pagesLost} of {document.pageCount} pages yielded no text and were not
          indexed — likely scanned images. OCR arrives at stage 16.2.
        </p>
      )}

      {/* A failure is durable, so the reason belongs on screen rather than
          only in the response that carried it. Since stage 1.3 there is no
          such response at all: this is the only place it appears.

          Stage 2.3 split it in two. The message alone does not say whether
          anything can be done — "is not a valid PDF" and "could not reach the
          agent" are both just strings — and the answer decides whether this
          row should offer a button or an explanation. */}
      {document.error && document.status === "failed" && (
        <FailureNotice document={document} />
      )}

      {/* A failure on a job that is still queued is a *past* attempt, not the
          outcome. It is rendered by the retry notices below, which say when
          the next attempt is due; showing the red terminal block here as well
          would read as "this is over". */}

      {/* ── The two non-terminal states, kept apart ───────────────────────────
          They mean different things to a user, and conflating them would hide
          the only clue that the queue is not draining. */}
      {/* ── The two kinds of "queued" ──────────────────────────────────────
          Identical over the wire until stage 2.1 added `attempts`. One is a
          document nobody has got to; the other is one that has failed and is
          waiting to try again. Showing the same text for both would hide a
          repeated failure behind a patient-looking label. */}
      {document.status === "queued" && document.attempts === 0 && (
        <p className="mt-1 text-xs leading-relaxed text-neutral-500">
          Waiting for a worker. If this does not change, nothing is draining
          the queue.
        </p>
      )}

      {document.status === "queued" && document.attempts > 0 && (
        <p className="mt-1 text-xs leading-relaxed text-amber-700">
          Attempt {document.attempts} failed
          {document.failureKind === "transient" &&
            " — the service was unavailable"}
          , retrying{retryIn(document.nextAttemptAt)}. Nothing is lost; the
          document is still queued.
        </p>
      )}

      {/* `processing` means a worker holds a lease on this job and is
          renewing it. Since stage 2.1 that is a genuine distinction rather
          than a hopeful one: a worker that stops renewing loses the job to a
          reaper within a lease period, and the row returns to `queued` with
          its `attempts` incremented.

          So the message no longer hedges about a worker having died. It is
          either working or about to be reclaimed, and both resolve without
          anyone doing anything. Two CHECK constraints guarantee the state
          cannot mean anything else: a `processing` job holds a lease, and a
          lease has an expiry. */}
      {document.status === "processing" && (
        <p className="mt-1 text-xs leading-relaxed text-amber-700">
          A worker is indexing this. If it stops, another one takes over
          automatically.
        </p>
      )}
    </li>
  );
}

/**
 * What a dead document says, and whether it offers a way out.
 *
 * ── The whole of stage 2.3's client half ────────────────────────────────────
 *
 * Two failures that look identical in the database — `status: "failed"` with
 * a string — and that need opposite things from whoever is reading:
 *
 *   permanent   the file is the problem. Say what is wrong with it. **No
 *               retry button**, because retrying queues an attempt guaranteed
 *               to fail the same way, and a button that cannot work teaches
 *               the user the system is flaky rather than that their file is
 *               unreadable.
 *
 *   transient   the system was the problem and it has probably passed. Offer
 *               the retry, because this one plausibly works now — and the
 *               person looking at this row usually does not have the original
 *               file to re-upload.
 *
 * `failureKind` is the only thing that distinguishes them, and it cannot be
 * derived here: the error message is prose written for a human.
 */
function FailureNotice({ document }: { document: DocumentRecord }) {
  const [retry, { isLoading, error }] = useRetryDocumentMutation();
  const recoverable = document.failureKind === "transient";

  return (
    <div
      className={cn(
        "mt-1 rounded border px-2 py-1.5 text-xs leading-relaxed",
        recoverable
          ? "border-amber-200 bg-amber-50 text-amber-800"
          : "border-red-200 bg-red-50 text-red-700",
      )}
    >
      <p>{document.error}</p>

      {recoverable && (
        <p className="mt-1 text-amber-700">
          This was the service, not the file
          {document.attempts > 1 && ` — ${document.attempts} attempts`}. It may
          work now.
        </p>
      )}

      {/* The button exists only for the recoverable case. A disabled or
          hidden-but-present control would still suggest the action is
          meaningful; there simply is not one for a file that cannot be read. */}
      {recoverable && (
        <button
          type="button"
          onClick={() => void retry(document.documentId)}
          disabled={isLoading}
          className="mt-1.5 rounded border border-amber-300 bg-white px-2 py-1 font-medium text-amber-800 transition-colors hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isLoading ? "Queueing…" : "Try again"}
        </button>
      )}

      {/* A 409 means the row changed under us — someone else retried it, or
          the list is a poll behind. The server's own words are better than a
          generic failure, because they say which. */}
      {error && (
        <p className="mt-1 text-red-700">{error.message}</p>
      )}

      {/* The honest ending for a file that cannot be indexed: nothing to try,
          and what would actually change the answer. */}
      {!recoverable && (
        <p className="mt-1 text-red-600">
          Retrying will not help — the file itself cannot be read. Upload a
          different copy, or a text-based PDF if this one is scanned.
        </p>
      )}
    </div>
  );
}

/**
 * "in 12s", " shortly", or "" when there is nothing useful to say.
 *
 * No timer and no `setInterval`: the list is polled every two seconds while
 * anything is unfinished, so each poll re-renders this and the number counts
 * down on its own. The backoff being *data in a row* rather than a sleep
 * inside a worker is what makes that possible.
 */
function retryIn(nextAttemptAt: string | null): string {
  if (nextAttemptAt === null) return " shortly";

  const seconds = Math.round(
    (new Date(nextAttemptAt).getTime() - Date.now()) / 1000,
  );
  return seconds > 0 ? ` in ${seconds}s` : " shortly";
}

function StatusBadge({ status }: { status: DocumentRecord["status"] }) {
  const label = status ?? "no attempt";

  return (
    <span
      className={cn(
        "flex-shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide",
        status === "done" && "bg-emerald-100 text-emerald-700",
        status === "failed" && "bg-red-100 text-red-700",
        // Deliberately different from `processing`: "nobody has started this"
        // and "someone is working on it" are different facts, and a user
        // watching a queue needs to know which one they are looking at.
        status === "queued" && "bg-neutral-100 text-neutral-600",
        status === "processing" && "bg-amber-100 text-amber-700",
        // A document with no job at all should be impossible — both rows are
        // written in one transaction. It renders rather than being hidden,
        // because a state that should not exist is worth seeing if it does.
        status === null && "bg-neutral-200 text-neutral-600",
      )}
    >
      {label}
    </span>
  );
}
