import { cn } from "@/lib/utils";
import type { Source } from "@/types";

interface SourceCardProps {
  source: Source;
}

/**
 * One retrieved chunk, with its page and score.
 *
 * Replaces the v0 `CitationCard`, which expected an `excerpt` field the API
 * does not send and a `documentTitle` that is actually a filename.
 *
 * **Every retrieved source renders, not only the cited ones.** A product UI
 * would show citations alone. This is a test harness, and the most common
 * question when an answer is wrong is "did retrieval miss the right chunk, or
 * did the model ignore it?" — which only the uncited sources can answer. An
 * uncited chunk scoring 0.82 and containing the answer is a *generation*
 * failure; no chunk above 0.4 is a *retrieval* failure. Those need completely
 * different fixes, and stage 3.2 turns that distinction into a measured
 * taxonomy.
 *
 * The score is shown raw and unformatted beyond three decimals. It is only
 * comparable within one answer, so it is not labelled "confidence" or drawn as
 * a bar — both would imply a meaning it does not have.
 */
export function SourceCard({ source }: SourceCardProps) {
  return (
    <div
      className={cn(
        "rounded-lg border px-3 py-2 text-sm transition-colors",
        source.cited
          ? "border-blue-200 bg-blue-50/60"
          : "border-neutral-200 bg-neutral-50",
      )}
    >
      <div className="flex items-center gap-2">
        {/* The marker, matching the [n] the model wrote in the answer. */}
        <span
          className={cn(
            "flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full text-xs font-semibold",
            source.cited
              ? "bg-blue-600 text-white"
              : "bg-neutral-200 text-neutral-600",
          )}
        >
          {source.marker}
        </span>

        <span className="min-w-0 flex-1 truncate font-medium text-neutral-700">
          {source.filename}
        </span>

        <span className="flex-shrink-0 text-xs text-neutral-500">
          p.{source.page}
        </span>

        <span
          className="flex-shrink-0 font-mono text-xs tabular-nums text-neutral-400"
          title="Cosine similarity — only comparable within this answer"
        >
          {source.score.toFixed(3)}
        </span>

        {!source.cited && (
          <span
            className="flex-shrink-0 rounded bg-neutral-200 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-neutral-500"
            title="Retrieved and shown to the model, but not referenced in the answer"
          >
            unused
          </span>
        )}
      </div>

      <p className="mt-1.5 whitespace-pre-wrap pl-7 text-xs leading-relaxed text-neutral-500">
        {source.text}
      </p>
    </div>
  );
}
