import { ChatInput } from "@/features/chat/components/ChatInput";
import { ChatWindow } from "@/features/chat/components/ChatWindow";
import { DocumentList } from "@/features/documents/components/DocumentList";
import { UploadPanel } from "@/features/documents/components/UploadPanel";
import { AppHeader } from "@/features/ui/components/AppHeader";
import { Sidebar } from "@/features/ui/components/Sidebar";

/**
 * The only page. Layout and composition — nothing else.
 *
 * No state, no selectors, no dispatch, no mutation hooks, and — notably — **no
 * `"use client"`**. Every child is a Client Component, but this file no longer
 * uses a hook or a handler, so it can stay a Server Component. That is not a
 * trick: it is the measurable result of each component owning its own data
 * access. The client boundary moved down to the components that need it.
 *
 * ── What the three layers changed here ──────────────────────────────────────
 *
 *   before   five `useState` calls, two hand-written hooks, nine props passed
 *            down, and a `handleAsk` that knew about the transcript
 *   after    six imports and some flexbox
 *
 * ── Why `Sidebar` takes children ────────────────────────────────────────────
 *
 * `Sidebar` is in `features/ui` and owns application chrome. Having it render
 * `<UploadPanel/>` and `<DocumentList/>` itself would be shorter here and
 * would make the ui feature depend on the documents feature. Composing at the
 * page keeps the dependency pointing the right way: the page knows about both
 * features, and neither feature knows about the other.
 */
export default function Page() {
  return (
    <div className="flex h-dvh overflow-hidden bg-white">
      <Sidebar>
        <UploadPanel />
        <DocumentList />
      </Sidebar>

      <div className="flex min-w-0 flex-1 flex-col">
        <AppHeader />

        <ChatWindow />

        <div className="border-t border-neutral-100 bg-white px-4 py-4">
          <div className="mx-auto max-w-3xl">
            {/* Not disabled when nothing is indexed. The backend answers that
                case honestly — "no documents have been indexed yet" — and
                being able to exercise that path from the UI is worth more than
                preventing it. */}
            <ChatInput />
            <p className="mt-2 text-center text-xs text-neutral-400">
              Answers come only from indexed documents. Every source shows its
              page — check it.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
