/**
 * query.ts — the `POST /query` boundary.
 *
 * Owns one endpoint, its wire format, and the one transformation that matters:
 * merging the API's two parallel arrays into a single source list.
 */

import { postJson } from "./api";
import type { Answer, Source } from "@/types";

/** Mirrors `Citation` in `agent/app/schemas/query.py`. Note: no text. */
interface CitationWire {
  marker: number;
  document_id: string;
  filename: string;
  page: number;
}

/** Mirrors `SourceChunk`. This is where the chunk text and score live. */
interface SourceWire {
  marker: number;
  document_id: string;
  filename: string;
  page: number;
  score: number;
  text: string;
}

interface QueryResponseWire {
  answer: string;
  citations: CitationWire[];
  sources: SourceWire[];
}

/**
 * Ask a question and get back an answer with its evidence.
 *
 * `topK` is omitted from the request when undefined rather than sent as null,
 * so the engine applies its own default. The frontend holds no opinion about
 * how many chunks retrieval should return — `rag` owns that, and a second
 * default here would be a second source of truth for the same setting.
 */
export async function ask(question: string, topK?: number): Promise<Answer> {
  const wire = await postJson<QueryResponseWire>(
    "/query",
    topK === undefined ? { question } : { question, top_k: topK },
  );

  // The merge. `citations` tells us which markers the model actually used;
  // `sources` carries every chunk it was shown, with the text and the score.
  // A Set rather than `.some()` inside the map, so this stays linear rather
  // than quadratic — irrelevant at five sources, free to get right.
  const citedMarkers = new Set(wire.citations.map((c) => c.marker));

  const sources: Source[] = wire.sources.map((s) => ({
    marker: s.marker,
    documentId: s.document_id,
    filename: s.filename,
    page: s.page,
    score: s.score,
    text: s.text,
    cited: citedMarkers.has(s.marker),
  }));

  return { text: wire.answer, sources };
}
