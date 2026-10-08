"use client";

import { useRef } from "react";

import { selectLatestUpload } from "@/features/documents/uploadsSlice";
import { useUploadDocumentMutation } from "@/services/documentsApi";
import { useAppSelector } from "@/store/hooks";

/**
 * The file picker, and the report of what ingestion actually did.
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
 * ── Why the numbers, not a success message ──────────────────────────────────
 *
 * The dangerous outcome at this stage is not a crash. It is a scanned PDF that
 * opens cleanly, yields no text, and reports success having indexed nothing.
 * The engine refuses that outright — but the *partial* case, ten pages with
 * three yielding text, is a real and quiet loss. The only way to notice it is
 * to put `pagesWithText` next to `pageCount` and let a human see the gap.
 */
export function UploadPanel() {
  const [uploadDocument, { isLoading, error }] = useUploadDocumentMutation();
  const latestUpload = useAppSelector(selectLatestUpload);

  const inputRef = useRef<HTMLInputElement>(null);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      // No `.unwrap()`: `uploadsSlice` records success via `matchFulfilled`,
      // and the failure is already in `error` below.
      void uploadDocument(file);
    }

    // Clear the input's value so selecting the same file again fires another
    // change event. Without this, re-uploading a file after fixing something
    // server-side silently does nothing, which is baffling to debug.
    e.target.value = "";
  };

  const document = latestUpload?.document ?? null;
  const pagesLost = document ? document.pageCount - document.pagesWithText : 0;

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
            Indexing…
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

      {/* Ingestion is synchronous at this stage, so the wait is real and can be
          minutes on a large document. Saying so beats a spinner that looks
          stuck — and the backend's 120s timeout is stage 1.3's trigger. */}
      {isLoading && (
        <p className="px-1 text-xs leading-relaxed text-neutral-400">
          Extracting, embedding and indexing. This runs synchronously, so a
          large PDF can take minutes.
        </p>
      )}

      {error && (
        <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs leading-relaxed text-red-700">
          {error.message}
        </p>
      )}

      {document && !isLoading && (
        <div className="rounded-lg border border-neutral-200 bg-white px-3 py-2 text-xs">
          <p className="truncate font-medium text-neutral-700">
            {document.filename}
          </p>
          <dl className="mt-1.5 grid grid-cols-2 gap-x-2 gap-y-0.5 text-neutral-500">
            <dt>Pages</dt>
            <dd className="text-right tabular-nums">{document.pageCount}</dd>
            <dt>With text</dt>
            <dd className="text-right tabular-nums">
              {document.pagesWithText}
            </dd>
            <dt>Chunks</dt>
            <dd className="text-right tabular-nums">{document.chunkCount}</dd>
            <dt>Characters</dt>
            <dd className="text-right tabular-nums">
              {document.charactersExtracted.toLocaleString()}
            </dd>
          </dl>

          {/* The policy decision the type deliberately does not encode: any gap
              at all is worth flagging, because those pages are not in the index
              and no question will ever find them. */}
          {pagesLost > 0 && (
            <p className="mt-2 rounded border border-amber-200 bg-amber-50 px-2 py-1.5 leading-relaxed text-amber-800">
              {pagesLost} of {document.pageCount} pages yielded no text and were
              not indexed — likely scanned images. OCR arrives at stage 16.2.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
