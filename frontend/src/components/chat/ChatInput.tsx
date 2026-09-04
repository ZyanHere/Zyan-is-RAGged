"use client";

import { useState, useRef, useEffect } from "react";
import { cn } from "@/lib/utils";

interface ChatInputProps {
  onSubmit: (content: string) => void;
  /** Abort the in-flight reply. */
  onStop: () => void;
  /** True from submit until the stream ends. */
  isStreaming: boolean;
  disabled?: boolean;
}

export function ChatInput({ onSubmit, onStop, isStreaming, disabled }: ChatInputProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);

  const handleSubmit = () => {
    const trimmed = value.trim();
    if (!trimmed || isStreaming || disabled) return;
    onSubmit(trimmed);
    setValue("");
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const canSubmit = value.trim().length > 0 && !isStreaming && !disabled;

  return (
    <div className="flex items-end gap-3 rounded-2xl border border-neutral-200 bg-white px-4 py-3 shadow-sm focus-within:border-blue-400 focus-within:ring-2 focus-within:ring-blue-100 transition-all">
      <textarea
        ref={textareaRef}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Ask a question…"
        rows={1}
        disabled={disabled}
        className="flex-1 resize-none bg-transparent text-sm text-neutral-800 placeholder:text-neutral-400 outline-none leading-relaxed disabled:opacity-50"
        aria-label="Chat message input"
      />

      {/* While streaming the send button becomes Stop. One control, one
          obvious action — never both at once. */}
      {isStreaming ? (
        <button
          onClick={onStop}
          aria-label="Stop generating"
          title="Stop generating"
          className="flex-shrink-0 flex h-8 w-8 items-center justify-center rounded-xl bg-neutral-800 text-white hover:bg-neutral-900 active:scale-95 transition-all"
        >
          <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="currentColor">
            <rect x="5" y="5" width="14" height="14" rx="2" />
          </svg>
        </button>
      ) : (
        <button
          onClick={handleSubmit}
          disabled={!canSubmit}
          aria-label="Send message"
          className={cn(
            "flex-shrink-0 flex h-8 w-8 items-center justify-center rounded-xl transition-all",
            canSubmit
              ? "bg-blue-600 text-white hover:bg-blue-700 active:scale-95"
              : "bg-neutral-100 text-neutral-400 cursor-not-allowed"
          )}
        >
          <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="22" y1="2" x2="11" y2="13" />
            <polygon points="22 2 15 22 11 13 2 9 22 2" />
          </svg>
        </button>
      )}
    </div>
  );
}
