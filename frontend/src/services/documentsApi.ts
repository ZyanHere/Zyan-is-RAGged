/**
 * The `/documents` endpoints.
 *
 * Owns both of them and the only place in the app that knows their wire
 * format. The `*Wire` interfaces are not exported, so nothing outside this
 * file can reach for `document_id` even by accident.
 */

import { baseApi } from "./baseApi";
import type {
  DocumentRecord,
  FailureKind,
  IngestionStatus,
  UploadResult,
} from "@/types";

/**
 * Exactly what the backend returns, snake_case and all.
 *
 * Mirrors `DocumentRead` in `backend/app/schemas/documents.py`. Hand-written,
 * so it can drift from the real API without anything complaining — the fix is
 * `@rtk-query/codegen-openapi` against the backend's `/openapi.json`, which
 * becomes worth the build step when the API is a published surface at stage
 * 19.1, or sooner if a field rename ever ships a silent bug.
 */
interface DocumentWire {
  document_id: string;
  filename: string;
  created_at: string;

  /**
   * **This said `"processing" | "done" | "failed"` until stage 2.1**, which
   * was wrong from the moment `queued` shipped at 1.3 — and TypeScript could
   * not catch it, because this interface is an assertion about JSON rather
   * than something the compiler checks against the server.
   *
   * It is `IngestionStatus` now, so the two cannot drift again without the
   * shared type changing. A generated client from the backend's OpenAPI
   * schema would remove the possibility entirely; that is stage 19.1's job.
   */
  status: IngestionStatus | null;

  page_count: number | null;
  pages_with_text: number | null;
  characters_extracted: number | null;
  chunk_count: number | null;
  error: string | null;
  failure_kind: FailureKind | null;
  attempts: number;
  next_attempt_at: string | null;
  finished_at: string | null;
}

/** The list endpoint's envelope. */
interface DocumentListWire {
  items: DocumentWire[];
}

function toRecord(wire: DocumentWire): DocumentRecord {
  return {
    documentId: wire.document_id,
    filename: wire.filename,
    createdAt: wire.created_at,
    status: wire.status,
    pageCount: wire.page_count,
    pagesWithText: wire.pages_with_text,
    charactersExtracted: wire.characters_extracted,
    chunkCount: wire.chunk_count,
    error: wire.error,
    failureKind: wire.failure_kind,
    attempts: wire.attempts,
    nextAttemptAt: wire.next_attempt_at,
    finishedAt: wire.finished_at,
  };
}

export const documentsApi = baseApi.injectEndpoints({
  endpoints: (builder) => ({
    /**
     * Every document the server knows about, newest first.
     *
     * **This is the endpoint that makes the architecture pay out.** The upload
     * mutation below has declared `invalidatesTags` since the day it was
     * written, when nothing provided that tag and the line was a no-op against
     * an empty cache. Now that this query provides it, the two halves connect:
     * a successful upload invalidates the list, the list refetches itself, and
     * the sidebar updates. No component subscribes to anything, no callback is
     * wired, no code was added to make it happen.
     *
     * It also replaces an entire Redux slice. Until this existed, the sidebar
     * showed a client-side log of what this tab had uploaded, which vanished
     * on refresh. The list is now server state and persists.
     *
     * ── Tag granularity ────────────────────────────────────────────────────
     *
     * Two kinds of tag are provided: one per document, and one for the list
     * itself (`id: "LIST"`). The distinction matters as soon as there is more
     * than one mutation:
     *
     *   adding a document    → invalidate LIST (the set changed)
     *   editing document X   → invalidate {id: X} (one row changed, the set
     *                          did not, so nothing else need refetch)
     *
     * Without the per-id tags, every write would refetch everything. Without
     * the LIST tag, adding a document would invalidate nothing, because no
     * existing id matches a row that did not exist yet.
     */
    listDocuments: builder.query<DocumentRecord[], void>({
      query: () => "/documents",
      transformResponse: (wire: DocumentListWire): DocumentRecord[] =>
        wire.items.map(toRecord),
      providesTags: (result) =>
        result
          ? [
              ...result.map(({ documentId }) => ({
                type: "Document" as const,
                id: documentId,
              })),
              { type: "Document" as const, id: "LIST" },
            ]
          : // An errored or absent result still provides the LIST tag, so a
            // later invalidation retries it. Returning nothing here would mean
            // a failed first load never recovers on its own.
            [{ type: "Document" as const, id: "LIST" }],
    }),

    /**
     * Hand one PDF to the server. **Does not wait for it to be indexed.**
     *
     * A mutation rather than a query: it changes server state, and its result
     * is not something the UI would look up again by key.
     *
     * ── What changed at stage 1.3 ──────────────────────────────────────────
     *
     * This used to block for the whole ingest — extraction, an embedding call
     * per batch, the vector write — so a large PDF sat here for minutes and
     * eventually hit the backend's 120-second timeout.
     *
     * The server now answers `202 Accepted` as soon as the upload is recorded,
     * in tens of milliseconds regardless of size. **So the resolved value of
     * this mutation is a document with `status: "queued"` and every count
     * `null`** — not a result, a receipt.
     *
     * The outcome arrives through `listDocuments`, which `useDocuments` polls
     * while anything is unfinished. That is why `invalidatesTags` matters more
     * than it used to: it is what starts the polling.
     *
     * A component reading `pageCount` from this mutation's `data` would
     * therefore render blanks forever and look broken. The numbers belong to
     * the list row now, which is where they actually arrive.
     *
     * ── What changed at stage 2.2 ──────────────────────────────────────────
     *
     * The server deduplicates by content hash, so an upload of bytes it
     * already holds queues nothing and answers `200 OK` rather than `202
     * Accepted`. Both carry the same body, so **the status code is the only
     * signal**, and this is the one place in the app that can see it.
     *
     * Hence `UploadResult` instead of a bare `DocumentRecord`: the document,
     * plus the one bit a component cannot derive from it.
     */
    uploadDocument: builder.mutation<UploadResult, File>({
      query: (file) => {
        const form = new FormData();

        // The field name must be exactly "file" — it matches the parameter in
        // `backend/app/api/routes/documents.py` and FastAPI resolves multipart
        // fields by name. Rename it and the request fails with a 422 about a
        // missing field.
        form.append("file", file);

        return { url: "/documents", method: "POST", body: form };
      },

      /**
       * `meta` carries the raw `Response`, which is where the status lives.
       *
       * `meta` is optional in RTK Query's types and genuinely can be absent —
       * a request that never reached the network has no response to report.
       * `meta?.response?.status === 200` therefore treats "we do not know" as
       * "not a duplicate", which is the safe default: it tells the user to
       * watch the row, and the row is correct either way.
       */
      transformResponse: (wire: DocumentWire, meta): UploadResult => ({
        document: toRecord(wire),
        alreadyIndexed: meta?.response?.status === 200,
      }),

      // The set of documents changed, so the list is stale. Only the list —
      // no existing document was modified, so nothing else needs refetching.
      //
      // Still correct for a duplicate, and worth a sentence because it looks
      // wasteful: a `200` changed nothing, so the refetch returns what the
      // cache already had. It is one request, and the alternative — skipping
      // invalidation when `alreadyIndexed` — would be wrong whenever the
      // duplicate matched a *failed* document, because that case did queue a
      // new attempt and the row's status has changed.
      invalidatesTags: [{ type: "Document", id: "LIST" }],
    }),

    /**
     * Queue another attempt at a document already on the server. Stage 2.3.
     *
     * The operator's half of the dead-letter queue. Without it, a document
     * that failed during an outage can only be revived by finding the
     * original file and uploading it again — and the person looking at the
     * list is usually not the person who has the file.
     *
     * ── Why it takes an id and not a file ──────────────────────────────────
     *
     * The bytes are already stored. Stage 1.3 put them in `document_uploads`
     * so a `202` could outlive the request that carried them, and this is the
     * second thing that storage buys: re-driving a document costs one row.
     *
     * ── The tags, and why the per-id one is included here ─────────────────
     *
     * `uploadDocument` invalidates only `LIST`, because the set of documents
     * changed and no existing row did. This is the opposite: the set is the
     * same and **one row changed** — `failed` became `queued`. Both tags are
     * invalidated because both facts are now stale, and the per-id tag is
     * what the detail view (when there is one) would be subscribed to.
     *
     * A `409` comes back when the document is already in flight. It surfaces
     * as `error` on the mutation like any other failure, with the server's
     * explanation, which is the honest thing to show — the button should not
     * have been offered, and saying so is better than failing silently.
     */
    retryDocument: builder.mutation<DocumentRecord, string>({
      query: (documentId) => ({
        url: `/documents/${documentId}/retry`,
        method: "POST",
      }),

      transformResponse: toRecord,

      invalidatesTags: (_result, _error, documentId) => [
        { type: "Document", id: documentId },
        { type: "Document", id: "LIST" },
      ],
    }),
  }),
});

export const {
  useListDocumentsQuery,
  useUploadDocumentMutation,
  useRetryDocumentMutation,
} = documentsApi;
