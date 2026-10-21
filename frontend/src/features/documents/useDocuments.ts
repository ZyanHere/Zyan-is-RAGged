"use client";

import { useMemo } from "react";

import { documentsApi, useListDocumentsQuery } from "@/services/documentsApi";
import { useAppSelector } from "@/store/hooks";
import type { DocumentRecord, IngestionStatus } from "@/types";

/**
 * The document list, polled only while something is still happening.
 *
 * ── Why this hook exists at all ─────────────────────────────────────────────
 *
 * Until stage 1.3 the upload request *was* the progress indicator: it stayed
 * open until the document was indexed, and its response carried the result. A
 * `202 Accepted` ends that. The server now says "recorded, not done", and the
 * only way to learn the outcome is to ask again.
 *
 * So the client grows its first real state machine, and this is it. Two
 * components read the list — `DocumentList` and `EmptyState` — and the
 * decision about when to poll has to be made once, not in each of them.
 *
 * ── Polling, and why it switches itself off ─────────────────────────────────
 *
 * A fixed interval would keep requesting the list forever, on an idle tab,
 * for a corpus nobody is changing. Polling only while a job is `queued` or
 * `processing` means the common case — everything finished — costs nothing.
 *
 * RTK Query treats `pollingInterval: 0` as "do not poll", so the switch is the
 * same expression that computes the interval. And because both components
 * subscribe to one cache entry, the library takes the lowest non-zero interval
 * among them: the other component does not have to know this is happening.
 *
 * ── Why the interval is read from the cache, not from this hook's result ────
 *
 * The obvious shape does not compile:
 *
 *     const result = useListDocumentsQuery(undefined, { pollingInterval });
 *     const pollingInterval = busy(result.data) ? 2_000 : 0;   // used before defined
 *
 * The two usual ways out, and why this one:
 *
 *   `useState` + `useEffect` on `result.data`
 *       Works, and is what most codebases do. It costs an extra render per
 *       transition and introduces a moment where the interval disagrees with
 *       the data it was derived from.
 *
 *   **Read the cache with the endpoint's own selector** ← chosen
 *       `documentsApi.endpoints.listDocuments.select()` reads the same cache
 *       entry the query writes, without subscribing to it. So the interval is
 *       derived from current state during render, with no effect, no extra
 *       state and no extra render.
 *
 * The selector is memoised because `select()` builds a new one on each call,
 * and an unstable selector throws away `useSelector`'s memoisation.
 */
const POLL_INTERVAL_MS = 2_000;

/**
 * States in which the server may still change its mind about a document.
 *
 * Mirrors `IngestionStatus.is_terminal` on the backend. The duplication is
 * real and deliberate: a shared schema is stage 19.1's problem, and until then
 * two short lists that must agree are cheaper than a code-generation step.
 *
 * `null` — a document with no job at all — is treated as terminal. It should
 * be impossible, and polling forever over an impossible state would turn a
 * data inconsistency into a permanent background request.
 */
const NON_TERMINAL: readonly IngestionStatus[] = ["queued", "processing"];

export function isSettled(document: DocumentRecord): boolean {
  return (
    document.status === null ||
    !NON_TERMINAL.includes(document.status as IngestionStatus)
  );
}

export interface UseDocumentsResult {
  documents: DocumentRecord[];
  isLoading: boolean;
  isError: boolean;
  errorMessage: string | null;
  /** True while at least one document is `queued` or `processing`. */
  isAnythingPending: boolean;
}

export function useDocuments(): UseDocumentsResult {
  const selectList = useMemo(
    () => documentsApi.endpoints.listDocuments.select(),
    [],
  );
  const cached = useAppSelector(selectList);

  const isAnythingPending = (cached.data ?? []).some(
    (document) => !isSettled(document),
  );

  const { data, isLoading, isError, error } = useListDocumentsQuery(undefined, {
    pollingInterval: isAnythingPending ? POLL_INTERVAL_MS : 0,
  });

  return {
    documents: data ?? [],
    isLoading,
    isError,
    // `baseApi` normalises every failure into `{ status, message }`, so this
    // does not need to know the difference between a network error, a timeout
    // and a 500.
    errorMessage:
      isError && error && "message" in error
        ? (error as { message: string }).message
        : null,
    isAnythingPending,
  };
}
