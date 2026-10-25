"use client";

import { useDocuments } from "@/features/documents/useDocuments";
import { cn } from "@/lib/utils";
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
          such response at all: this is the only place it appears. */}
      {document.error && (
        <p className="mt-1 text-xs leading-relaxed text-red-600">
          {document.error}
        </p>
      )}

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
          Attempt {document.attempts} failed — retrying
          {retryIn(document.nextAttemptAt)}. Nothing is lost; the document is
          still queued.
        </p>
      )}

      {/* `processing` with no finish time means a worker claimed it and has
          not come back — either still working, or dead. Nothing can tell those
          apart yet, and nothing retries; that is stage 2.1. A database CHECK
          constraint guarantees the state cannot mean anything else. */}
      {document.status === "processing" && (
        <p className="mt-1 text-xs leading-relaxed text-amber-700">
          A worker is indexing this — or stopped partway. Nothing retries it
          yet.
        </p>
      )}
    </li>
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
