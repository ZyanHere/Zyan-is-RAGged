"use client";

import { useEffect, useRef, useState } from "react";

import { useAskQuestion } from "@/features/chat/useAskQuestion";
import { cn } from "@/lib/utils";

/**
 * The question composer.
 *
 * **Takes no props.** It reads what it needs from the feature hook, which is
 * the point of layer 4: a component that needs store data subscribes to it
 * rather than having it handed down. `page.tsx` renders `<ChatInput />` and
 * knows nothing about asking questions.
 *
 * ── The one piece of state that stays local ─────────────────────────────────
 *
 * `value` — the textarea's contents — is deliberately *not* in Redux, and this
 * is the clearest example of the rule. It changes on every keystroke, and
 * nothing outside this component ever reads it. In the store it would dispatch
 * an action per character, flood DevTools, and re-render every subscriber in
 * the app for a value only this `<textarea>` cares about.
 *
 * The test: **does anything outside this component need to read it?** For a
 * draft message, no. The moment it does — a draft restored across navigation,
 * say — it stops being local.
 *
 * The Stop button is gone. In v0 it aborted an SSE stream, which genuinely
 * stopped generation. With a single JSON response there is nothing useful to
 * abort: the work is already happening on the server, so cancelling would hide
 * the answer without saving the cost. A disabled input and a spinner is the
 * honest signal.
 */
export function ChatInput() {
  const { askQuestion, isAsking } = useAskQuestion();

  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);

  const handleSubmit = () => {
    const trimmed = value.trim();
    if (!trimmed || isAsking) return;
    askQuestion(trimmed);
    setValue("");
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const canSubmit = value.trim().length > 0 && !isAsking;

  return (
    <div className="flex items-end gap-3 rounded-2xl border border-neutral-200 bg-white px-4 py-3 shadow-sm transition-all focus-within:border-blue-400 focus-within:ring-2 focus-within:ring-blue-100">
      <textarea
        ref={textareaRef}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Ask a question about your documents…"
        rows={1}
        disabled={isAsking}
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
        {isAsking ? (
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
