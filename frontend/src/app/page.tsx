"use client";

import { useCallback, useState } from "react";

import { ChatInput } from "@/components/chat/ChatInput";
import { ChatWindow } from "@/components/chat/ChatWindow";
import { UploadPanel } from "@/components/documents/UploadPanel";
import { Sidebar } from "@/components/layout/Sidebar";
import { useAsk } from "@/hooks/useAsk";
import { useUpload } from "@/hooks/useUpload";
import type { IngestedDocument, Message } from "@/types";

/**
 * The only page.
 *
 * ── State ownership ─────────────────────────────────────────────────────────
 *
 * This component is the single owner of both pieces of domain state:
 *
 *   documents — read by Sidebar and (as a boolean) by EmptyState. Two
 *               siblings, which is why it is lifted to their common parent
 *               rather than living in one of them.
 *   messages  — read by ChatWindow.
 *
 * Nothing below holds a copy. Children receive values and callbacks, and the
 * hooks own only their own request lifecycle (`isAsking`, `isUploading`,
 * `error`), never domain data. That division is what makes "one owner per
 * piece of state" true rather than aspirational — the v0 `useChat` held
 * `messages` while this page separately held `storedConversations` and merged
 * the two with a `useMemo`, which is two owners of overlapping data.
 *
 * ── Why not Redux or Context ────────────────────────────────────────────────
 *
 * Six values, one route, at most three consumers each, deepest prop path is two
 * levels. Nothing to drill through and nothing shared across unrelated
 * surfaces, so a store would be ceremony over `useState`.
 *
 * The triggers that change this, each tied to an observable change in the
 * system rather than a preference:
 *
 *   stage 1.2  `GET /documents` exists. The document list stops being client
 *              state and becomes a *cache of server state* — it can go stale
 *              and must refetch after an upload. That is TanStack Query's
 *              problem, not `useState`'s, and it is the next thing to adopt.
 *   stage 1.3  upload returns 202 + a job id and the UI must poll until the
 *              job is terminal. Hand-rolled polling with setInterval and
 *              cleanup is about forty fiddly lines; one option object there.
 *   stage 5.2  `currentUser` is read by the header, the sidebar and every
 *              guarded route, and changes twice a session. That is the shape
 *              React Context is actually for.
 *
 * Redux Toolkit only earns itself if *client* state later goes cross-route —
 * realistically the platform phase, possibly never.
 */
export default function Page() {
  // ── Owned state ───────────────────────────────────────────────────────────
  const [documents, setDocuments] = useState<IngestedDocument[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // ── Request lifecycles ────────────────────────────────────────────────────
  const { upload, isUploading, error: uploadError } = useUpload();
  const { submit, isAsking, error: askError } = useAsk();

  const handleSelectFile = useCallback(
    async (file: File) => {
      const document = await upload(file);
      // `null` means the upload failed; the hook is already holding the message
      // and `UploadPanel` is already rendering it. Nothing to add here.
      if (document) {
        setDocuments((prev) => [document, ...prev]);
      }
    },
    [upload],
  );

  const handleAsk = useCallback(
    async (question: string) => {
      // Show the question immediately, before the round trip. Retrieval plus
      // generation is seconds on a free-tier model, and a composer that clears
      // with nothing appearing reads as a dropped message.
      const userMessage: Message = {
        id: crypto.randomUUID(),
        role: "user",
        content: question,
        createdAt: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, userMessage]);

      const answer = await submit(question);
      if (!answer) return;

      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: answer.text,
          sources: answer.sources,
          createdAt: new Date().toISOString(),
        },
      ]);
    },
    [submit],
  );

  const lastUploaded = documents[0] ?? null;

  return (
    <div className="flex h-dvh overflow-hidden bg-white">
      <Sidebar
        documents={documents}
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      >
        <UploadPanel
          onSelectFile={handleSelectFile}
          isUploading={isUploading}
          error={uploadError}
          lastResult={lastUploaded}
        />
      </Sidebar>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-neutral-200 px-4 py-3">
          <button
            type="button"
            onClick={() => setSidebarOpen(true)}
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

        <ChatWindow
          messages={messages}
          isAsking={isAsking}
          error={askError}
          hasDocuments={documents.length > 0}
          onPromptClick={handleAsk}
        />

        <div className="border-t border-neutral-100 bg-white px-4 py-4">
          <div className="mx-auto max-w-3xl">
            {/* Not disabled when nothing is indexed. The backend answers that
                case honestly — "no documents have been indexed yet" — and
                being able to exercise that path from the UI is worth more than
                preventing it. */}
            <ChatInput onSubmit={handleAsk} isBusy={isAsking} />
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
