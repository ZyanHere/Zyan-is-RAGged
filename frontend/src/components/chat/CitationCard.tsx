import type { Citation } from "@/types";

interface CitationCardProps {
  citation: Citation;
  index: number;
}

export function CitationCard({ citation, index }: CitationCardProps) {
  return (
    <div className="rounded-lg border border-neutral-200 bg-neutral-50 px-3 py-2 text-sm">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="flex-shrink-0 flex h-5 w-5 items-center justify-center rounded-full bg-blue-100 text-xs font-semibold text-blue-700">
            {index + 1}
          </span>
          <span className="truncate font-medium text-neutral-700">
            {citation.documentTitle}
          </span>
          {citation.pageNumber && (
            <span className="flex-shrink-0 text-neutral-400">p.{citation.pageNumber}</span>
          )}
        </div>
      </div>
      <p className="mt-1.5 pl-7 text-neutral-500 italic leading-relaxed line-clamp-3">
        &ldquo;{citation.excerpt}&rdquo;
      </p>
    </div>
  );
}
