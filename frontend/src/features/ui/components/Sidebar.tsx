"use client";

import type { ReactNode } from "react";

import { selectSidebarOpen, sidebarClosed } from "@/features/ui/uiSlice";
import { cn } from "@/lib/utils";
import { useAppDispatch, useAppSelector } from "@/store/hooks";

/**
 * The application's left shell.
 *
 * Connects to `uiSlice` for its own open/closed state, and takes everything
 * else as `children`. That split is the feature boundary doing real work:
 * `features/ui` owns chrome and knows nothing about documents, so it never
 * imports `SessionUpload` or a documents selector.
 *
 * The alternative — rendering `<UploadPanel/>` and `<DocumentList/>` in here
 * directly — would be fewer lines in `page.tsx` and would make the ui feature
 * depend on the documents feature. Composition at the page keeps the
 * dependency pointing the way it should: the page knows about both features;
 * neither feature knows about the other.
 *
 * ── In v0 this listed conversations ─────────────────────────────────────────
 *
 * Conversations do not exist at stage 1.1 — the API is stateless and
 * single-turn — so that list was a client fiction with a "TODO: load when the
 * backend is ready" handler. Documents are the thing the system actually has.
 */
export function Sidebar({ children }: { children?: ReactNode }) {
  const isOpen = useAppSelector(selectSidebarOpen);
  const dispatch = useAppDispatch();

  return (
    <>
      {isOpen && (
        <div
          className="fixed inset-0 z-20 bg-black/30 lg:hidden"
          onClick={() => dispatch(sidebarClosed())}
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
            onClick={() => dispatch(sidebarClosed())}
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

        <div className="flex flex-1 flex-col gap-3 overflow-y-auto px-3 py-3">
          {children}
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
