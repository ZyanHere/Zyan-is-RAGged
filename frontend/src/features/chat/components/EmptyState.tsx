"use client";

import { selectHasUploads } from "@/features/documents/uploadsSlice";
import { useAskQuestion } from "@/features/chat/useAskQuestion";
import { useAppSelector } from "@/store/hooks";

/**
 * Shown before the first question.
 *
 * The v0 version offered four suggested prompts unconditionally. With nothing
 * indexed those are fiction — every one returns "no documents have been
 * indexed yet". So the state branches: upload first, then suggestions.
 *
 * ── A cross-feature read, on purpose ────────────────────────────────────────
 *
 * This lives in `features/chat` and reads `selectHasUploads` from
 * `features/documents`. That is fine and worth stating plainly: **feature
 * folders organise code, they do not forbid reads.** Trying to enforce
 * isolation here would mean threading a boolean down from `page.tsx` purely to
 * avoid an import — reintroducing the prop drilling layer 4 exists to remove.
 *
 * What a feature boundary *should* prevent is one feature mutating another's
 * state. Reading a selector is a dependency on a shape; dispatching another
 * feature's actions is a dependency on its behaviour. The first is cheap, the
 * second is where coupling hurts.
 *
 * The prompts themselves are deliberately generic. Document-aware suggestions
 * would mean asking a model what a document contains before the user asks
 * anything — a real feature with a real cost and no trigger yet.
 */
const SUGGESTED_PROMPTS = [
  "What is this document about?",
  "Summarise the key points",
  "What are the main findings?",
  "List any dates or figures mentioned",
];

export function EmptyState() {
  const hasDocuments = useAppSelector(selectHasUploads);
  const { askQuestion } = useAskQuestion();

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-8 px-4 py-16 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-500 to-violet-600 shadow-lg">
        <svg
          className="h-8 w-8 text-white"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M9 12h6M9 16h6M17 3H7a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V5a2 2 0 00-2-2z" />
          <path d="M13 3v4h4" />
        </svg>
      </div>

      {hasDocuments ? (
        <>
          <div className="space-y-2">
            <h2 className="text-xl font-semibold text-neutral-800">
              Ask a question
            </h2>
            <p className="max-w-sm text-sm text-neutral-500">
              Answers come only from the indexed documents, and every claim
              carries the page it came from.
            </p>
          </div>

          <div className="grid w-full max-w-lg grid-cols-1 gap-2 sm:grid-cols-2">
            {SUGGESTED_PROMPTS.map((prompt) => (
              <button
                key={prompt}
                type="button"
                onClick={() => askQuestion(prompt)}
                className="rounded-xl border border-neutral-200 bg-white px-4 py-3 text-left text-sm text-neutral-600 shadow-sm transition-all hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700"
              >
                {prompt}
              </button>
            ))}
          </div>
        </>
      ) : (
        <div className="space-y-2">
          <h2 className="text-xl font-semibold text-neutral-800">
            Upload a PDF to begin
          </h2>
          <p className="max-w-sm text-sm text-neutral-500">
            Nothing is indexed yet. Use{" "}
            <span className="font-medium text-neutral-700">Upload PDF</span> in
            the sidebar — the document is extracted, chunked, embedded and
            indexed before the upload returns.
          </p>
        </div>
      )}
    </div>
  );
}
