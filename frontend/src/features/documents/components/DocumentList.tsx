"use client";

import { useListDocumentsQuery } from "@/services/documentsApi";
import { cn } from "@/lib/utils";
import type { DocumentRecord } from "@/types";

/**
 * Every document the server has, with the state of its last ingestion attempt.
 *
 * ── This used to read a Redux slice ────────────────────────────────────────
 *
 * Until stage 1.2 it rendered `state.uploads` — a client-side log of what this
 * browser tab had uploaded, which vanished on refresh and knew nothing about
 * uploads made anywhere else.
 *
 * It now reads server state. The list persists, and it shows failures too:
 * stage 1.2 records a rejected PDF as a document with a failed job, so the
 * reason it was rejected is still here tomorrow instead of disappearing with
 * the response that carried it.
 *
 * The slice was deleted rather than kept alongside. A client mirror of server
 * data is the duplication the whole client/server state split exists to
 * prevent.
 *
 * ── Why calling the query here is cheap ────────────────────────────────────
 *
 * `EmptyState` calls `useListDocumentsQuery()` as well. That is not two
 * requests: RTK Query caches by endpoint and argument, so both components
 * subscribe to one cache entry and one fetch. Components ask for what they
 * need, and the library works out that it is the same thing.
 */
export function DocumentList() {
  const { data: documents, isLoading, isError, error } = useListDocumentsQuery();

  if (isLoading) {
    return (
      <p className="px-1 py-2 text-xs text-neutral-400">Loading documents…</p>
    );
  }

  if (isError) {
    return (
      <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs leading-relaxed text-red-700">
        {error && "message" in error
          ? (error as { message: string }).message
          : "Could not load documents."}
      </p>
    );
  }

  if (!documents || documents.length === 0) {
    return (
      <p className="px-1 py-2 text-xs leading-relaxed text-neutral-400">
        No documents indexed yet.
      </p>
    );
  }

  return (
    <div>
      <p className="mb-1.5 px-1 text-xs font-medium uppercase tracking-wide text-neutral-400">
        Indexed · {documents.length}
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

      {document.status === "done" && (
        <p className="mt-0.5 text-xs tabular-nums text-neutral-400">
          {document.pageCount} pages · {document.chunkCount} chunks
          {pagesLost > 0 && (
            <span className="text-amber-600">
              {" · "}
              {pagesLost} empty
            </span>
          )}
        </p>
      )}

      {/* A failure is now durable, so the reason belongs on screen rather than
          only in the toast that appeared when it happened. */}
      {document.error && (
        <p className="mt-1 text-xs leading-relaxed text-red-600">
          {document.error}
        </p>
      )}

      {/* `processing` with no finish time means the ingestion started and
          never completed — the process was killed, or it is still running.
          A database CHECK constraint guarantees the state cannot mean
          anything else. Nothing retries it yet; that is stage 2.1. */}
      {document.status === "processing" && (
        <p className="mt-1 text-xs leading-relaxed text-amber-700">
          Still indexing, or interrupted. Nothing retries it yet.
        </p>
      )}
    </li>
  );
}

function StatusBadge({ status }: { status: DocumentRecord["status"] }) {
  const label = status ?? "no attempt";

  return (
    <span
      className={cn(
        "flex-shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide",
        status === "done" && "bg-emerald-100 text-emerald-700",
        status === "failed" && "bg-red-100 text-red-700",
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
