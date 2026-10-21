"use client";

import { useRef } from "react";

import { useUploadDocumentMutation } from "@/services/documentsApi";

/**
 * The file picker, and confirmation that the server took the file.
 *
 * Takes no props. It calls the mutation directly rather than going through a
 * feature hook the way chat does — **because it is the only uploader.** The
 * `useAskQuestion` hook exists to share one mutation entry between two
 * components; here there is nothing to share, and a hook would be indirection
 * for its own sake.
 *
 * If a second upload entry point ever appears — a drag-and-drop zone on the
 * empty state, say — this becomes a `useUploadDocument` hook with a
 * `fixedCacheKey`, for exactly the reason spelled out in `useAskQuestion`.
 *
 * ── Why this panel no longer reports what ingestion did ─────────────────────
 *
 * It used to show page count, pages-with-text, chunks and characters, with a
 * warning when pages yielded no text. All of that came from the upload
 * response, because the request stayed open until the document was indexed.
 *
 * Stage 1.3 ended that. The response is now a `202` receipt: `status:
 * "queued"` and every count `null`. Rendering those fields here would show
 * blanks forever and look broken.
 *
 * **So the numbers moved to the document row**, which is where they now
 * arrive — including the pages-with-text gap, the one that catches a scanned
 * PDF indexing almost nothing. Nothing was lost, and a duplicate display went
 * away with it.
 *
 * What is left here is the only thing this component can still truthfully say:
 * the file reached the server and is recorded.
 */
export function UploadPanel() {
  // `data` is this component's last upload — now a receipt rather than a
  // result. `isLoading` covers only the upload itself, which is milliseconds,
  // so the spinner is honest about what it is waiting for.
  const [uploadDocument, { isLoading, error, data: lastUpload }] =
    useUploadDocumentMutation();

  const inputRef = useRef<HTMLInputElement>(null);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      // No `.unwrap()`. On success the `invalidatesTags` on this mutation
      // marks the document list stale, `DocumentList` refetches, and because
      // the new row is `queued`, `useDocuments` starts polling. Nothing here
      // needs to know any of that happened. On failure the message is already
      // in `error` below.
      void uploadDocument(file);
    }

    // Clear the input's value so selecting the same file again fires another
    // change event. Without this, re-uploading a file after fixing something
    // server-side silently does nothing, which is baffling to debug.
    e.target.value = "";
  };

  return (
    <div className="flex flex-col gap-2">
      <input
        ref={inputRef}
        type="file"
        // A filter, not a guarantee — the picker can be bypassed, and the
        // engine checks the actual PDF magic bytes rather than trusting either
        // the extension or this attribute.
        accept="application/pdf,.pdf"
        onChange={handleChange}
        className="hidden"
        aria-hidden="true"
        tabIndex={-1}
      />

      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        disabled={isLoading}
        className="flex w-full items-center justify-center gap-2 rounded-xl border border-neutral-200 bg-white px-3 py-2.5 text-sm font-medium text-neutral-700 shadow-sm transition-all hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700 disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:border-neutral-200 disabled:hover:bg-white disabled:hover:text-neutral-700"
      >
        {isLoading ? (
          <>
            <svg
              className="h-4 w-4 animate-spin"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
            >
              <path d="M21 12a9 9 0 1 1-6.219-8.56" />
            </svg>
            {/* "Uploading", not "Indexing". The request only carries the file
                now, and claiming otherwise would be the UI lying about which
                part is slow. */}
            Uploading…
          </>
        ) : (
          <>
            <svg
              className="h-4 w-4"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="17 8 12 3 7 8" />
              <line x1="12" y1="3" x2="12" y2="15" />
            </svg>
            Upload PDF
          </>
        )}
      </button>

      {error && (
        <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs leading-relaxed text-red-700">
          {error.message}
        </p>
      )}

      {/* The receipt. Deliberately says nothing about the document's contents,
          because at this point the server does not know them either. */}
      {lastUpload && !isLoading && !error && (
        <p className="rounded-lg border border-neutral-200 bg-white px-3 py-2 text-xs leading-relaxed text-neutral-500">
          <span className="font-medium text-neutral-700">
            {lastUpload.filename}
          </span>{" "}
          is queued. Indexing happens in the background — watch its row below
          for the result.
        </p>
      )}
    </div>
  );
}
