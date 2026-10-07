"use client";

import { useCallback, useState } from "react";

import { errorMessage } from "@/services/api";
import { ask } from "@/services/query";
import type { Answer } from "@/types";

/**
 * The query *request lifecycle* — and nothing else.
 *
 * Same division as `useUpload`: this hook owns `isAsking` and `error`, the
 * transcript lives in `page.tsx`.
 *
 * Gone from the v0 `useChat`, and worth naming so the absences are deliberate
 * rather than forgotten:
 *
 * - **no `AbortController`** — nothing streams, so there is no partial output
 *   to stop. A Stop button would abort an HTTP request whose work is already
 *   happening server-side, which stops you seeing the answer without stopping
 *   the cost. Honest UI is a disabled input and a spinner.
 * - **no `isReasoning`** — that existed to explain the silence while a
 *   reasoning model thought out loud before emitting answer text. With a single
 *   JSON response there is no mid-flight signal to report.
 * - **no conversation id** — stage 1.1 is stateless and single-turn. The
 *   server is told the question and nothing else.
 *
 * All three come back if streaming returns. They are preserved at the
 * `v0-chat-app` tag rather than kept here as dead code.
 */
export function useAsk() {
  const [isAsking, setIsAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = useCallback(
    async (question: string): Promise<Answer | null> => {
      setError(null);
      setIsAsking(true);
      try {
        return await ask(question);
      } catch (err) {
        setError(errorMessage(err));
        return null;
      } finally {
        setIsAsking(false);
      }
    },
    [],
  );

  const clearError = useCallback(() => setError(null), []);

  return { submit, isAsking, error, clearError };
}
