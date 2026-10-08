/**
 * `POST /query`.
 *
 * Owns the endpoint, its wire format, and the one transformation that matters:
 * merging the API's two parallel arrays into a single source list.
 */

import { baseApi } from "./baseApi";
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

export interface AskArgs {
  question: string;
  /** Omitted means "let the engine decide" — `rag` owns that default. */
  topK?: number;
}

export const queryApi = baseApi.injectEndpoints({
  endpoints: (builder) => ({
    /**
     * Ask a question and get an answer with its evidence.
     *
     * **A mutation, despite having no side effects on the server.** Two
     * reasons it is not modelled as a query:
     *
     * - its result is not addressable by a key the UI would look up again; the
     *   same question asked twice is a new interaction, not a cache hit.
     * - caching answers in the browser would pre-empt **stage 9.1**, which is
     *   the cache-aside module. Answer caching belongs server-side, where it
     *   can be keyed per tenant, measured, and invalidated correctly when a
     *   document is re-indexed — the problems stages 9.2 and 9.3 exist to
     *   teach. A client cache would hide all of them.
     */
    ask: builder.mutation<Answer, AskArgs>({
      query: ({ question, topK }) => ({
        url: "/query",
        method: "POST",
        // `top_k` is omitted rather than sent as null, so the engine applies
        // its own default. The frontend holds no opinion about how many chunks
        // retrieval should return.
        body: topK === undefined ? { question } : { question, top_k: topK },
      }),

      transformResponse: (wire: QueryResponseWire): Answer => {
        // The merge. `citations` says which markers the model used; `sources`
        // carries every chunk it was shown, with the text and the score.
        //
        // A Set rather than `.some()` inside the map, so this stays linear
        // rather than quadratic — irrelevant at five sources, free to get
        // right, and it stops being irrelevant when stage 4.4 retrieves fifty
        // candidates to rerank.
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
      },
    }),
  }),
});

export const { useAskMutation } = queryApi;
