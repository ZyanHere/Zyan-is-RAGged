"use client";

import { useCallback } from "react";

import { questionAsked } from "@/features/chat/chatSlice";
import { useAskMutation } from "@/services/queryApi";
import { useAppDispatch } from "@/store/hooks";

/**
 * Asking a question, as one operation.
 *
 * Two components start a question — the composer, and the suggested prompts in
 * the empty state — and both need the same two steps in the same order:
 * record the user's turn, then fire the request. A hook is the right shape for
 * that: it is the feature's verb, usable anywhere, with no container component
 * in between.
 *
 * ── Why `fixedCacheKey`, and the bug it prevents ────────────────────────────
 *
 * Every call to `useAskMutation()` creates its **own** subscription with its
 * own request id and its own `isLoading`. Two components calling it
 * independently get two unrelated pieces of state — so a question fired from
 * the empty state would leave the composer's spinner idle, and the composer
 * would stay enabled while a request was in flight.
 *
 * Nothing errors. The UI is just quietly wrong, in a way that only shows up
 * when you use the second entry point.
 *
 * `fixedCacheKey` makes every caller share one mutation entry, so `isAsking`
 * means "a question is in flight" for the whole feature rather than "a question
 * I personally started". That is the correct meaning here, and it is the
 * reason this hook exists rather than each component calling the mutation.
 *
 * One consequence worth knowing: a shared entry is not removed when a single
 * subscriber unmounts, and `reset()` affects everyone. Both are what we want.
 */
const ASK_CACHE_KEY = "ask-question";

export function useAskQuestion() {
  const dispatch = useAppDispatch();
  const [ask, { isLoading, error }] = useAskMutation({
    fixedCacheKey: ASK_CACHE_KEY,
  });

  const askQuestion = useCallback(
    (question: string) => {
      // The user's turn is dispatched explicitly because it genuinely
      // originates here — no API event produces it, and it has to appear
      // before the request so the composer does not clear into silence.
      dispatch(questionAsked(question));

      // No `.unwrap()` and no `await`: success is `chatSlice`'s job via
      // `matchFulfilled`, and failure is already in `error` below. Without
      // `.unwrap()` this promise never rejects, so there is nothing to catch.
      void ask({ question });
    },
    [ask, dispatch],
  );

  return {
    askQuestion,
    isAsking: isLoading,
    /** Already normalised by the base query — always a string worth showing. */
    error: error?.message ?? null,
  };
}
