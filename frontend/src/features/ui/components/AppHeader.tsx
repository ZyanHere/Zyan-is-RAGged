"use client";

import { sidebarOpened } from "@/features/ui/uiSlice";
import { useAppDispatch } from "@/store/hooks";

/**
 * The top bar.
 *
 * Extracted from `page.tsx` so that the page holds no dispatch of its own. It
 * is small, and that is fine — a component that exists to own one interaction
 * is still better than a page that owns one interaction *and* composes the
 * layout.
 *
 * This is also the component that makes `sidebarOpen` worth having in Redux
 * rather than in `page.tsx`. The open button lives here, the close button
 * lives in `Sidebar`, and neither is an ancestor of the other. Lifting the
 * state to their common parent is exactly what we were doing before, and it
 * meant the page held state purely so two unrelated children could share it.
 *
 * At stage 5.2 this grows a user menu and a sign-out, and the sidebar toggle
 * is already where it belongs.
 */
export function AppHeader() {
  const dispatch = useAppDispatch();

  return (
    <header className="flex items-center gap-3 border-b border-neutral-200 px-4 py-3">
      <button
        type="button"
        onClick={() => dispatch(sidebarOpened())}
        className="text-neutral-400 hover:text-neutral-700 lg:hidden"
        aria-label="Open sidebar"
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
          <line x1="3" y1="6" x2="21" y2="6" />
          <line x1="3" y1="12" x2="21" y2="12" />
          <line x1="3" y1="18" x2="21" y2="18" />
        </svg>
      </button>

      <h1 className="text-sm font-medium text-neutral-500">myRAG</h1>

      <span className="ml-auto text-xs text-neutral-400">
        stage 1.1 · synchronous
      </span>
    </header>
  );
}
