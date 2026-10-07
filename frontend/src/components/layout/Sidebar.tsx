"use client";

import type { ReactNode } from "react";

import { cn } from "@/lib/utils";
import type { IngestedDocument } from "@/types";

interface SidebarProps {
  documents: IngestedDocument[];
  isOpen: boolean;
  onClose: () => void;
  /** The upload control. Passed in so this component knows nothing about uploading. */
  children?: ReactNode;
}

/**
 * The document list, and a slot for the upload control.
 *
 * In v0 this listed conversations. Conversations do not exist at stage 1.1 —
 * the API is stateless and single-turn — so the list would have been a client
 * fiction with a "TODO: load when backend is ready" handler. Documents are the
 * thing the system actually has, which makes the sidebar useful instead of
 * decorative.
 *
 * **This list is per browser tab and clears on refresh.** There is no
 * `GET /documents` yet: with no database, the backend has nothing to list from.
 * The index itself survives — Qdrant has the chunks on disk and questions will
 * still find them — it is only the *knowledge of what was uploaded* that is
 * lost. That gap is stage 1.2's trigger, and the footer says so on screen
 * rather than only in a comment.
 *
 * The upload control arrives as `children` rather than as props. The
 * alternative — threading `onSelectFile`, `isUploading`, `error` and
 * `lastResult` through this component to reach `UploadPanel` — is four props
 * drilled one level for nothing, and it would re-render the whole sidebar on
 * every upload state change.
 */
export function Sidebar({
  documents,
  isOpen,
  onClose,
  children,
}: SidebarProps) {
  return (
    <>
      {isOpen && (
        <div
          className="fixed inset-0 z-20 bg-black/30 lg:hidden"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-30 flex w-72 flex-col border-r border-neutral-200 bg-neutral-50 transition-transform duration-200",
          "lg:static lg:translate-x-0",
          isOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex items-center justify-between border-b border-neutral-200 px-4 py-4">
          <div className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-blue-500 to-violet-600">
              <span className="text-xs font-bold text-white">R</span>
            </div>
            <span className="font-semibold tracking-tight text-neutral-800">
              myRAG
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-neutral-400 hover:text-neutral-600 lg:hidden"
            aria-label="Close sidebar"
          >
            <svg
              className="h-5 w-5"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {/* Upload slot */}
        <div className="px-3 py-3">{children}</div>

        <div className="flex flex-1 flex-col gap-4 overflow-y-auto px-3 py-2">
          {documents.length === 0 ? (
            <p className="px-1 py-2 text-xs leading-relaxed text-neutral-400">
              No documents indexed in this session.
            </p>
          ) : (
            <div>
              <p className="mb-1.5 px-1 text-xs font-medium uppercase tracking-wide text-neutral-400">
                Indexed this session
              </p>
              <ul className="flex flex-col gap-1">
                {documents.map((doc) => (
                  <li
                    key={doc.documentId}
                    className="rounded-lg border border-neutral-200 bg-white px-3 py-2"
                  >
                    <p
                      className="truncate text-sm text-neutral-700"
                      title={doc.filename}
                    >
                      {doc.filename}
                    </p>
                    <p className="mt-0.5 text-xs tabular-nums text-neutral-400">
                      {doc.pageCount} pages · {doc.chunkCount} chunks
                      {doc.pagesWithText < doc.pageCount && (
                        <span className="text-amber-600">
                          {" · "}
                          {doc.pageCount - doc.pagesWithText} empty
                        </span>
                      )}
                    </p>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <div className="border-t border-neutral-200 px-4 py-3">
          <p className="text-xs leading-relaxed text-neutral-400">
            This list is local to the browser tab and clears on refresh. The
            index itself persists — a durable document record arrives with
            Postgres at stage 1.2.
          </p>
        </div>
      </aside>
    </>
  );
}
