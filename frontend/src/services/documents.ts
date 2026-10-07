/**
 * documents.ts — the `POST /documents` boundary.
 *
 * Owns one endpoint, and owns the only place in the app that knows what its
 * wire format looks like. `IngestResponseWire` is not exported, so no component
 * can reach for `document_id` even by accident.
 */

import { postForm } from "./api";
import type { IngestedDocument } from "@/types";

/**
 * Exactly what the backend returns, snake_case and all.
 *
 * This mirrors `IngestResponse` in `agent/app/schemas/documents.py`. Keeping it
 * hand-written means it can drift from the real API without anything
 * complaining — the alternative is generating it from the backend's
 * `/openapi.json`, which is worth doing when the API becomes a published
 * surface at stage 19.1, or sooner if a field rename ever ships a silent bug.
 */
interface IngestResponseWire {
  document_id: string;
  filename: string;
  page_count: number;
  pages_with_text: number;
  characters_extracted: number;
  chunk_count: number;
}

/**
 * Upload one PDF and wait for it to be indexed.
 *
 * **This blocks for as long as ingestion takes** — extraction, then an
 * embedding call per batch of chunks, then the vector write. A ten-page PDF is
 * a few seconds; a three-hundred-page one will sit here for minutes and
 * eventually time out at the backend's 120-second limit.
 *
 * That is not an oversight to work around in the UI. It is stage 1.1's known
 * defect and the observed trigger for the `202 Accepted` + job-polling design
 * in stage 1.3. The honest thing for the UI to do is show that it is waiting.
 */
export async function uploadDocument(file: File): Promise<IngestedDocument> {
  const form = new FormData();

  // The field name must be exactly "file" — it matches the parameter name in
  // `agent/app/api/routes/documents.py` (`file: UploadFile = File(...)`), and
  // FastAPI resolves multipart fields by name. Rename it here and the request
  // fails with a 422 about a missing field.
  form.append("file", file);

  const wire = await postForm<IngestResponseWire>("/documents", form);

  return {
    documentId: wire.document_id,
    filename: wire.filename,
    pageCount: wire.page_count,
    pagesWithText: wire.pages_with_text,
    charactersExtracted: wire.characters_extracted,
    chunkCount: wire.chunk_count,
    // Client-side, because there is no server-side document list to read a
    // timestamp from yet. Stage 1.2 replaces this with a real `created_at`.
    uploadedAt: new Date().toISOString(),
  };
}
