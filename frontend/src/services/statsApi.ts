/**
 * `GET /stats` — is ingestion healthy right now?
 *
 * Owns the one endpoint and the only place in the app that knows its wire
 * format, same rule as `documentsApi`.
 *
 * ── Why this is a separate file and not part of documentsApi ────────────────
 *
 * It answers a different question about a different thing. `documentsApi` is
 * about *your documents*; this is about *the pipeline*, and at stage 5.1 the
 * first becomes per-tenant while the second does not. Splitting them now costs
 * one file and means that stage is not a refactor.
 *
 * It shares `baseApi`, so there is still one cache, one middleware and one
 * error normaliser.
 */

import { baseApi } from "./baseApi";
import type { IngestionStats } from "@/types";

/** Exactly what the backend returns. Mirrors `IngestionStatsResponse`. */
interface StatsWire {
  queue: {
    claimable: number;
    waiting_for_retry: number;
    oldest_age_seconds: number | null;
  };
  in_flight: number;
  done: number;
  dead_letter: { total: number; permanent: number; transient: number };
  duration: { p50_seconds: number | null; p95_seconds: number | null };
}

function toStats(wire: StatsWire): IngestionStats {
  return {
    claimable: wire.queue.claimable,
    waitingForRetry: wire.queue.waiting_for_retry,
    oldestQueuedAgeSeconds: wire.queue.oldest_age_seconds,
    inFlight: wire.in_flight,
    done: wire.done,
    deadLetter: {
      total: wire.dead_letter.total,
      permanent: wire.dead_letter.permanent,
      transient: wire.dead_letter.transient,
    },
    durationP50Seconds: wire.duration.p50_seconds,
    durationP95Seconds: wire.duration.p95_seconds,
  };
}

export const statsApi = baseApi.injectEndpoints({
  endpoints: (builder) => ({
    /**
     * A snapshot of the pipeline.
     *
     * ── Why it provides the `Document` LIST tag ───────────────────────────
     *
     * Every one of these numbers is derived from the same rows the document
     * list shows. An upload, a retry or a worker finishing a job all
     * invalidate `{ type: "Document", id: "LIST" }` already — so subscribing
     * to the same tag means the header refreshes with the list, for free,
     * with no new invalidation anywhere.
     *
     * Without it the counts would be a second, independently stale copy of
     * facts the list has just refreshed: the row would say `done` while the
     * header still claimed something was queued, and the user would have two
     * contradictory answers on one screen.
     */
    ingestionStats: builder.query<IngestionStats, void>({
      query: () => "/stats",
      transformResponse: toStats,
      providesTags: [{ type: "Document", id: "LIST" }],
    }),
  }),
});

export const { useIngestionStatsQuery } = statsApi;
