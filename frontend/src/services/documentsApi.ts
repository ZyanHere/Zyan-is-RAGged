/**
 * `POST /documents`.
 *
 * Owns the endpoint and the only place in the app that knows its wire format.
 * `IngestResponseWire` is not exported, so nothing outside this file can reach
 * for `document_id` even by accident.
 */

import { baseApi } from "./baseApi";
import type { IngestedDocument } from "@/types";

/**
 * Exactly what the backend returns, snake_case and all.
 *
 * Mirrors `IngestResponse` in `agent/app/schemas/documents.py`. Hand-written,
 * so it can drift from the real API without anything complaining — the fix is
 * `@rtk-query/codegen-openapi` against the backend's `/openapi.json`, which
 * becomes worth the build step when the API is a published surface at stage
 * 19.1, or sooner if a field rename ever ships a silent bug.
 */
interface IngestResponseWire {
  document_id: string;
  filename: string;
  page_count: number;
  pages_with_text: number;
  characters_extracted: number;
  chunk_count: number;
}

export const documentsApi = baseApi.injectEndpoints({
  endpoints: (builder) => ({
    /**
     * Upload one PDF and wait for it to be indexed.
     *
     * A mutation rather than a query: it changes server state, and its result
     * is not something the UI would look up again by key.
     *
     * **This blocks for as long as ingestion takes** — extraction, an
     * embedding call per batch of chunks, then the vector write. Ten pages is
     * a few seconds; three hundred will sit here for minutes and eventually
     * hit the backend's 120-second timeout.
     *
     * That is not an oversight to paper over in the UI. It is stage 1.1's
     * known defect and the observed trigger for the `202 Accepted` plus
     * job-polling design at stage 1.3, where this becomes a mutation returning
     * a job id and a *query* polling its status.
     */
    uploadDocument: builder.mutation<IngestedDocument, File>({
      query: (file) => {
        const form = new FormData();

        // The field name must be exactly "file" — it matches the parameter in
        // `agent/app/api/routes/documents.py` (`file: UploadFile = File(...)`)
        // and FastAPI resolves multipart fields by name. Rename it and the
        // request fails with a 422 about a missing field.
        form.append("file", file);

        return { url: "/documents", method: "POST", body: form };
      },

      // Wire shape to domain shape, in one place. Components never see
      // snake_case.
      transformResponse: (wire: IngestResponseWire): IngestedDocument => ({
        documentId: wire.document_id,
        filename: wire.filename,
        pageCount: wire.page_count,
        pagesWithText: wire.pages_with_text,
        charactersExtracted: wire.characters_extracted,
        chunkCount: wire.chunk_count,
      }),

      // A no-op today — nothing provides this tag, because there is no
      // document list to invalidate. At stage 1.2 the list query declares
      // `providesTags: ["Document"]` and this line starts refetching it after
      // every successful upload, with no further change here.
      invalidatesTags: ["Document"],
    }),
  }),
});

export const { useUploadDocumentMutation } = documentsApi;
