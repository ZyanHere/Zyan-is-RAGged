"use client";

import { useEffect, useRef } from "react";
import { MessageBubble } from "./MessageBubble";
import { LoadingDots } from "@/components/ui/LoadingDots";
import { EmptyState } from "./EmptyState";
import type { Message } from "@/types";

interface ChatWindowProps {
  messages: Message[];
  /** Reply currently arriving, rendered as an extra bubble below `messages`. */
  streamingContent: string | null;
  isLoading: boolean;
  /** Model is thinking; no answer text yet. */
  isReasoning: boolean;
  error: string | null;
  onPromptClick: (prompt: string) => void;
}

export function ChatWindow({
  messages,
  streamingContent,
  isLoading,
  isReasoning,
  error,
  onPromptClick,
}: ChatWindowProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  // Only auto-scroll while the user is already at the bottom. Yanking someone
  // back down while they are reading earlier messages is the single most
  // irritating behaviour a chat UI can have.
  const stickToBottom = useRef(true);

  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    stickToBottom.current = distanceFromBottom < 80;
  };

  useEffect(() => {
    if (stickToBottom.current) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, streamingContent, isLoading]);

  const hasContent = messages.length > 0 || streamingContent !== null;
  if (!hasContent && !isLoading) {
    return <EmptyState onPromptClick={onPromptClick} />;
  }

  return (
    <div
      ref={scrollRef}
      onScroll={handleScroll}
      className="flex-1 overflow-y-auto px-4 py-6"
    >
      <div className="mx-auto flex max-w-2xl flex-col gap-6">
        {messages.map((message) => (
          <MessageBubble key={message.id} message={message} />
        ))}

        {/* The reply being streamed. Kept out of `messages` so that appending a
            token re-renders only this bubble, not the whole history. */}
        {streamingContent !== null && (
          <MessageBubble
            message={{
              id: "streaming",
              role: "assistant",
              content: streamingContent,
              createdAt: new Date().toISOString(),
              isStreaming: true,
            }}
          />
        )}

        {/* Waiting for the first token. Retrieval and model latency both live
            here, so this can be several seconds. */}
        {isLoading && streamingContent === null && (
          <div className="flex items-start gap-3">
            <div className="mt-1 flex-shrink-0 h-7 w-7 rounded-full bg-gradient-to-br from-blue-500 to-violet-600 flex items-center justify-center">
              <span className="text-xs font-bold text-white select-none">R</span>
            </div>
            <div className="flex items-center gap-2 rounded-2xl border border-neutral-200 bg-white shadow-sm px-4 py-3">
              <LoadingDots />
              {isReasoning && (
                <span className="text-xs text-neutral-400">Thinking…</span>
              )}
            </div>
          </div>
        )}

        {error && (
          <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        <div ref={bottomRef} />
      </div>
    </div>
  );
}
