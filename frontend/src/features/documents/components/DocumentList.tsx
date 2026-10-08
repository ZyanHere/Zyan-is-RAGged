"use client";

import { selectUploads } from "@/features/documents/uploadsSlice";
import { useAppSelector } from "@/store/hooks";

/**
 * What this session uploaded.
 *
 * Extracted out of `Sidebar`, which had been rendering it inline. The split
 * matters for more than tidiness: `Sidebar` belongs to `features/ui` and is
 * application chrome, while this list is document data. Leaving them merged
 * meant the chrome re-rendered on every upload and the ui feature knew the
 * shape of a `SessionUpload`.
 *
 * ── What clears on refresh, and what does not ───────────────────────────────
 *
 * This list is `state.uploads`, which lives only in memory. Reload the tab and
 * it is empty — but the *index* is untouched. Qdrant still has the chunks on
 * disk and questions still find them. Only the knowledge of what was uploaded
 * is gone.
 *
 * That gap is exactly what stage 1.2 closes, and the footer in `Sidebar` says
 * so on screen rather than only in a comment. At that point this component
 * stops reading a slice and starts reading a `useListDocumentsQuery()` — the
 * data moves from client state to server state, and this is the file that
 * changes.
 */
export function DocumentList() {
  const uploads = useAppSelector(selectUploads);

  if (uploads.length === 0) {
    return (
      <p className="px-1 py-2 text-xs leading-relaxed text-neutral-400">
        No documents indexed in this session.
      </p>
    );
  }

  return (
    <div>
      <p className="mb-1.5 px-1 text-xs font-medium uppercase tracking-wide text-neutral-400">
        Indexed this session
      </p>
      <ul className="flex flex-col gap-1">
        {uploads.map((upload) => {
          const { document } = upload;
          const pagesLost = document.pageCount - document.pagesWithText;

          return (
            <li
              // The upload's own id, not the document's. At stage 2.2,
              // content-addressed idempotency makes re-uploading the same file
              // return the same document id — two entries would then share a
              // key and React would reuse the wrong node.
              key={upload.id}
              className="rounded-lg border border-neutral-200 bg-white px-3 py-2"
            >
              <p
                className="truncate text-sm text-neutral-700"
                title={document.filename}
              >
                {document.filename}
              </p>
              <p className="mt-0.5 text-xs tabular-nums text-neutral-400">
                {document.pageCount} pages · {document.chunkCount} chunks
                {pagesLost > 0 && (
                  <span className="text-amber-600">
                    {" · "}
                    {pagesLost} empty
                  </span>
                )}
              </p>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
