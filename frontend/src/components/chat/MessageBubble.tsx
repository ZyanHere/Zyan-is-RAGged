import { cn } from "@/lib/utils";
import { CitationCard } from "./CitationCard";
import type { Message } from "@/types";

interface MessageBubbleProps {
  message: Message;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";

  return (
    <div className={cn("flex w-full gap-3", isUser ? "justify-end" : "justify-start")}>
      {/* Avatar — assistant only */}
      {!isUser && (
        <div className="mt-1 flex-shrink-0 h-7 w-7 rounded-full bg-gradient-to-br from-blue-500 to-violet-600 flex items-center justify-center">
          <span className="text-xs font-bold text-white select-none">R</span>
        </div>
      )}

      <div className={cn("flex flex-col gap-2 max-w-[75%]", isUser && "items-end")}>
        {/* Bubble */}
        <div
          className={cn(
            "rounded-2xl px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap",
            isUser
              ? "bg-blue-600 text-white rounded-br-sm"
              : "bg-white border border-neutral-200 text-neutral-800 shadow-sm rounded-bl-sm"
          )}
        >
          {message.content}
        </div>

        {/* Citations */}
        {!isUser && message.citations && message.citations.length > 0 && (
          <div className="flex flex-col gap-1.5 w-full">
            <span className="text-xs font-medium text-neutral-400 uppercase tracking-wide">
              Sources
            </span>
            {message.citations.map((citation, i) => (
              <CitationCard key={citation.id} citation={citation} index={i} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
