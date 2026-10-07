"use client";

import { useEffect, useRef } from "react";

import { EmptyState } from "./EmptyState";
import { MessageBubble } from "./MessageBubble";
import { LoadingDots } from "@/components/ui/LoadingDots";
import type { Message } from "@/types";

interface ChatWindowProps {
  messages: Message[];
  /** A question is in flight. */
  isAsking: boolean;
  error: string | null;
  hasDocuments: boolean;
  onPromptClick: (prompt: string) => void;
}

/**
 * The scrolling transcript.
 *
 * `streamingContent` and `isReasoning` are gone — there is no partial reply to
 * render as a separate bubble, so an answer appears in one piece and the
 * waiting state is a single spinner.
 *
 * The scroll behaviour is kept from v0 and worth keeping: auto-scroll only
 * while the reader is already near the bottom. Yanking someone back down while
 * they are reading a source they scrolled up to check is the most irritating
 * thing a transcript UI can do, and in this UI people *will* scroll up to read
 * sources.
 */
export function ChatWindow({
  messages,
  isAsking,
  error,
  hasDocuments,
  onPromptClick,
}: ChatWindowProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
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
  }, [messages, isAsking]);

  if (messages.length === 0 && !isAsking && !error) {
    return (
      <EmptyState hasDocuments={hasDocuments} onPromptClick={onPromptClick} />
    );
  }

  return (
    <div
      ref={scrollRef}
      onScroll={handleScroll}
      className="flex-1 overflow-y-auto px-4 py-6"
    >
      <div className="mx-auto flex max-w-3xl flex-col gap-6">
        {messages.map((message) => (
          <MessageBubble key={message.id} message={message} />
        ))}

        {/* Embedding the question, searching, then generating — all of it
            happens behind this one spinner, and on a free-tier model it can be
            several seconds. Stage 10.2's tracing is what eventually tells you
            which part of the wait was which. */}
        {isAsking && (
          <div className="flex items-start gap-3">
            <div className="mt-1 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-violet-600">
              <span className="select-none text-xs font-bold text-white">
                R
              </span>
            </div>
            <div className="flex items-center gap-2 rounded-2xl border border-neutral-200 bg-white px-4 py-3 shadow-sm">
              <LoadingDots />
              <span className="text-xs text-neutral-400">
                Retrieving and answering…
              </span>
            </div>
          </div>
        )}

        {error && (
          <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm leading-relaxed text-red-700">
            {error}
          </div>
        )}

        <div ref={bottomRef} />
      </div>
    </div>
  );
}
