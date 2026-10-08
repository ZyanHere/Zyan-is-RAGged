"use client";

import { useEffect, useRef } from "react";

import { LoadingDots } from "@/components/ui/LoadingDots";
import { selectMessages } from "@/features/chat/chatSlice";
import { useAskQuestion } from "@/features/chat/useAskQuestion";
import { useAppSelector } from "@/store/hooks";

import { EmptyState } from "./EmptyState";
import { MessageBubble } from "./MessageBubble";

/**
 * The scrolling transcript.
 *
 * Reads the transcript and the in-flight state directly, so `page.tsx` renders
 * `<ChatWindow />` with no props at all. The five it used to take —
 * `messages`, `isAsking`, `error`, `hasDocuments`, `onPromptClick` — are now
 * each read by whichever component actually uses them, and the last two went
 * to `EmptyState`, which is the only thing that ever wanted them.
 *
 * That removes the one piece of genuine prop drilling the app had: this
 * component used to accept `hasDocuments` and `onPromptClick` purely to hand
 * them to `EmptyState`, without reading either.
 *
 * ── Subscription scope ──────────────────────────────────────────────────────
 *
 * `useAppSelector(selectMessages)` re-renders this subtree when the transcript
 * changes, and typing in the composer no longer re-renders it at all — the
 * draft is local to `ChatInput`. Before layer 4, every keystroke's state lived
 * above both components and re-rendered the lot.
 *
 * The scroll behaviour is kept from v0 and worth keeping: auto-scroll only
 * while the reader is already near the bottom. Yanking someone back down while
 * they are reading a source they scrolled up to check is the most irritating
 * thing a transcript UI can do — and in this UI people *will* scroll up to
 * read sources.
 */
export function ChatWindow() {
  const messages = useAppSelector(selectMessages);
  const { isAsking, error } = useAskQuestion();

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
    return <EmptyState />;
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
            happens behind this one spinner, and on a free-tier model that is
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
