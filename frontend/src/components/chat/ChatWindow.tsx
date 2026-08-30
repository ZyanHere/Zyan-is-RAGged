"use client";

import { useEffect, useRef } from "react";
import { MessageBubble } from "./MessageBubble";
import { LoadingDots } from "@/components/ui/LoadingDots";
import { EmptyState } from "./EmptyState";
import type { Message } from "@/types";

interface ChatWindowProps {
  messages: Message[];
  isLoading: boolean;
  error: string | null;
  onPromptClick: (prompt: string) => void;
}

export function ChatWindow({ messages, isLoading, error, onPromptClick }: ChatWindowProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  if (messages.length === 0 && !isLoading) {
    return <EmptyState onPromptClick={onPromptClick} />;
  }

  return (
    <div className="flex-1 overflow-y-auto px-4 py-6">
      <div className="mx-auto flex max-w-2xl flex-col gap-6">
        {messages.map((message) => (
          <MessageBubble key={message.id} message={message} />
        ))}

        {/* Loading indicator */}
        {isLoading && (
          <div className="flex items-start gap-3">
            <div className="mt-1 flex-shrink-0 h-7 w-7 rounded-full bg-gradient-to-br from-blue-500 to-violet-600 flex items-center justify-center">
              <span className="text-xs font-bold text-white select-none">R</span>
            </div>
            <div className="rounded-2xl border border-neutral-200 bg-white shadow-sm px-4 py-3">
              <LoadingDots />
            </div>
          </div>
        )}

        {/* Error banner */}
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
