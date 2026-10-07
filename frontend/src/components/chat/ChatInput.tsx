"use client";

import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

interface ChatInputProps {
  onSubmit: (question: string) => void;
  /** A question is in flight. */
  isBusy: boolean;
  disabled?: boolean;
  placeholder?: string;
}

/**
 * The question composer.
 *
 * The Stop button is gone. In v0 it aborted an SSE stream, which genuinely
 * stopped generation. With a single JSON response there is nothing to abort
 * usefully — the work is already happening on the server, so cancelling the
 * request would hide the answer without saving the cost. A disabled input and a
 * spinner is the honest signal.
 */
export function ChatInput({
  onSubmit,
  isBusy,
  disabled,
  placeholder,
}: ChatInputProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);

  const isBlocked = isBusy || disabled;

  const handleSubmit = () => {
    const trimmed = value.trim();
    if (!trimmed || isBlocked) return;
    onSubmit(trimmed);
    setValue("");
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const canSubmit = value.trim().length > 0 && !isBlocked;

  return (
    <div className="flex items-end gap-3 rounded-2xl border border-neutral-200 bg-white px-4 py-3 shadow-sm transition-all focus-within:border-blue-400 focus-within:ring-2 focus-within:ring-blue-100">
      <textarea
        ref={textareaRef}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder ?? "Ask a question about your documents…"}
        rows={1}
        disabled={isBlocked}
        className="flex-1 resize-none bg-transparent text-sm leading-relaxed text-neutral-800 outline-none placeholder:text-neutral-400 disabled:opacity-50"
        aria-label="Question"
      />

      <button
        type="button"
        onClick={handleSubmit}
        disabled={!canSubmit}
        aria-label="Ask"
        className={cn(
          "flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-xl transition-all",
          canSubmit
            ? "bg-blue-600 text-white hover:bg-blue-700 active:scale-95"
            : "cursor-not-allowed bg-neutral-100 text-neutral-400",
        )}
      >
        {isBusy ? (
          <svg
            className="h-4 w-4 animate-spin"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
          >
            <path d="M21 12a9 9 0 1 1-6.219-8.56" />
          </svg>
        ) : (
          <svg
            className="h-4 w-4"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <line x1="22" y1="2" x2="11" y2="13" />
            <polygon points="22 2 15 22 11 13 2 9 22 2" />
          </svg>
        )}
      </button>
    </div>
  );
}
