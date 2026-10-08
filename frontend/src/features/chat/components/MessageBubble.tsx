import { cn } from "@/lib/utils";
import { SourceCard } from "./SourceCard";
import type { Message } from "@/types";

interface MessageBubbleProps {
  message: Message;
}

/**
 * One turn in the transcript.
 *
 * Two changes from v0: the streaming caret is gone (nothing streams at this
 * stage), and the sources block renders every retrieved chunk rather than only
 * the cited ones — see `SourceCard` for why.
 *
 * The header line counts both, because "3 of 5 cited" is itself a signal. All
 * five cited means the model used everything it was given; zero cited on a
 * confident-sounding answer means it answered from its own training data and
 * the grounding instruction failed, which is exactly what stage 17.2 exists to
 * catch programmatically.
 */
export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const sources = message.sources ?? [];
  const citedCount = sources.filter((s) => s.cited).length;

  return (
    <div
      className={cn("flex w-full gap-3", isUser ? "justify-end" : "justify-start")}
    >
      {!isUser && (
        <div className="mt-1 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-violet-600">
          <span className="select-none text-xs font-bold text-white">R</span>
        </div>
      )}

      <div
        className={cn(
          "flex min-w-0 flex-col gap-2",
          isUser ? "max-w-[75%] items-end" : "w-full max-w-[85%]",
        )}
      >
        <div
          className={cn(
            "whitespace-pre-wrap rounded-2xl px-4 py-3 text-sm leading-relaxed",
            isUser
              ? "rounded-br-sm bg-blue-600 text-white"
              : "rounded-bl-sm border border-neutral-200 bg-white text-neutral-800 shadow-sm",
          )}
        >
          {message.content}
        </div>

        {!isUser && sources.length > 0 && (
          <div className="flex w-full flex-col gap-1.5">
            <span className="text-xs font-medium uppercase tracking-wide text-neutral-400">
              Retrieved · {citedCount} of {sources.length} cited
            </span>
            {sources.map((source) => (
              <SourceCard
                key={`${source.documentId}-${source.marker}`}
                source={source}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
