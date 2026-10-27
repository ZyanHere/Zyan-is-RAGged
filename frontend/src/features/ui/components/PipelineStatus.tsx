"use client";

import { useDocuments } from "@/features/documents/useDocuments";
import { cn } from "@/lib/utils";
import { useIngestionStatsQuery } from "@/services/statsApi";

/**
 * Queue depth and dead-letter count, in the header. Stage 2.4.
 *
 * ── Why this exists ─────────────────────────────────────────────────────────
 *
 * Stage 2.3 built a dead-letter list and told nobody to open it. Both of that
 * stage's defects were found by going and looking — a corrupt PDF fed in by
 * hand, a valid one uploaded with the agent stopped — and nothing reported
 * either. A page you have to remember to visit is a page you visit after
 * someone complains.
 *
 * So the number comes to you. Zero is invisible; anything else is not.
 *
 * ── Why it renders nothing when everything is fine ──────────────────────────
 *
 * A permanent "0 failed, 0 queued" is a badge that trains you to ignore it,
 * and the day it says 3 you will not notice. A thing that appears only when
 * it has something to say keeps its ability to say it.
 *
 * ── Why it polls on the documents' schedule and not its own ─────────────────
 *
 * `useDocuments` already decided when the server is worth asking: while
 * anything is `queued` or `processing`, and not otherwise. A second timer here
 * would poll an idle tab forever for a corpus nobody is changing — the exact
 * thing that hook exists to avoid — and the two would drift out of step, so
 * the header and the list would disagree about the same instant.
 *
 * The query also provides `{ type: "Document", id: "LIST" }`, so an upload or
 * a retry refreshes these numbers through the invalidation that already
 * exists. The polling is only for changes **this tab did not cause** — a
 * worker finishing a job in another process.
 */
const POLL_INTERVAL_MS = 2_000;

export function PipelineStatus() {
  const { isAnythingPending } = useDocuments();

  const { data: stats } = useIngestionStatsQuery(undefined, {
    pollingInterval: isAnythingPending ? POLL_INTERVAL_MS : 0,
  });

  if (!stats) return null;

  const queued = stats.claimable + stats.waitingForRetry;
  const dead = stats.deadLetter.total;

  // A stalled queue is the thing depth alone cannot show: three jobs that have
  // not moved in a minute is a worker problem, three moving steadily is not.
  const stalled =
    stats.inFlight === 0 &&
    stats.claimable > 0 &&
    (stats.oldestQueuedAgeSeconds ?? 0) > 60;

  if (queued === 0 && dead === 0) return null;

  return (
    <div className="flex items-center gap-2 text-xs">
      {queued > 0 && (
        <span
          className={cn(
            "rounded px-1.5 py-0.5 tabular-nums",
            stalled
              ? "bg-amber-100 text-amber-800"
              : "bg-neutral-100 text-neutral-600",
          )}
          title={
            stalled
              ? `Oldest has waited ${Math.round(
                  stats.oldestQueuedAgeSeconds ?? 0,
                )}s with nothing in flight — is a worker running?`
              : `${stats.claimable} claimable, ${stats.waitingForRetry} waiting to retry`
          }
        >
          {queued} queued{stalled && " · stalled"}
        </span>
      )}

      {dead > 0 && (
        <a
          href="#documents"
          className="rounded bg-red-100 px-1.5 py-0.5 tabular-nums text-red-700 hover:bg-red-200"
          title={`${stats.deadLetter.transient} worth retrying, ${stats.deadLetter.permanent} that will not succeed`}
        >
          {dead} failed
        </a>
      )}
    </div>
  );
}
