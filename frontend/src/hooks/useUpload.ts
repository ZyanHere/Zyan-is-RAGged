"use client";

import { useCallback, useState } from "react";

import { errorMessage } from "@/services/api";
import { uploadDocument } from "@/services/documents";
import type { IngestedDocument } from "@/types";

/**
 * The upload *request lifecycle* — and nothing else.
 *
 * This hook owns `isUploading` and `error`, because those exist only for the
 * duration of one request and no other part of the app has an opinion about
 * them. It deliberately does **not** own the list of uploaded documents.
 *
 * That list lives in `page.tsx`, because two siblings read it: the sidebar
 * shows it, and the empty state branches on whether it is empty. Keeping
 * domain data out of the hook is what makes "one owner per piece of state"
 * true rather than aspirational — if the hook held the array *and* the page
 * held a copy, we would be back to reconciling two sources of truth, which is
 * exactly the smell the v0 `useChat` had.
 *
 * So `upload` returns the document and lets the caller decide what to do with
 * it. When stage 1.2 adds `GET /documents`, this is the hook that TanStack
 * Query replaces — the list becomes a server cache, and caching, refetching
 * after an upload, and invalidation stop being hand-rolled.
 */
export function useUpload() {
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const upload = useCallback(
    async (file: File): Promise<IngestedDocument | null> => {
      setError(null);
      setIsUploading(true);
      try {
        return await uploadDocument(file);
      } catch (err) {
        setError(errorMessage(err));
        return null;
      } finally {
        // `finally` rather than duplicating this in both branches: the button
        // must re-enable on failure too, or one bad PDF locks the UI.
        setIsUploading(false);
      }
    },
    [],
  );

  const clearError = useCallback(() => setError(null), []);

  return { upload, isUploading, error, clearError };
}
