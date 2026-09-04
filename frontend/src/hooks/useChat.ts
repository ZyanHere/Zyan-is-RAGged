"use client";

import { useCallback, useRef, useState } from "react";
import type { Conversation, Message } from "@/types";
import { createConversation, streamMessage } from "@/services/chat";

interface UseChatReturn {
  /** Completed messages only. */
  messages: Message[];
  /** Text of the reply currently arriving, or null when nothing is streaming. */
  streamingContent: string | null;
  conversation: Conversation | null;
  /** Request sent, but no text has arrived yet. */
  isLoading: boolean;
  /** True from submit until the stream ends — what the Stop button keys off. */
  isStreaming: boolean;
  /** The model is thinking but has produced no answer text yet. */
  isReasoning: boolean;
  error: string | null;
  submit: (content: string) => Promise<void>;
  stop: () => void;
  startNewConversation: () => void;
}

export function useChat(): UseChatReturn {
  const [messages, setMessages] = useState<Message[]>([]);
  const [streamingContent, setStreamingContent] = useState<string | null>(null);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [isReasoning, setIsReasoning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Aborting this closes the HTTP connection, which propagates all the way to
  // the model — Stop actually stops generation rather than hiding the output.
  const abortRef = useRef<AbortController | null>(null);


  const startNewConversation = useCallback(() => {
    abortRef.current?.abort();
    setMessages([]);
    setStreamingContent(null);
    setConversation(null);
    setError(null);
    setIsLoading(false);
    setIsStreaming(false);
    setIsReasoning(false);
  }, []);

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const submit = useCallback(
    async (content: string) => {
      if (!content.trim() || isStreaming) return;
      setError(null);

      // Create the conversation on the first message.
      let currentConv = conversation;
      if (!currentConv) {
        currentConv = await createConversation(content.slice(0, 60));
        setConversation(currentConv);
      }

      // Show the user's message immediately, before the network round trip.
      const userMessage: Message = {
        id: crypto.randomUUID(),
        role: "user",
        content,
        createdAt: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, userMessage]);

      // Local, not refs: these live only for this call. The reply is tracked
      // here as well as in state because the last setState may not have been
      // applied by the time we finalise.
      let accumulated = "";
      let meta: { id: string; createdAt: string } | null = null;

      setStreamingContent(null);
      setIsLoading(true);
      setIsStreaming(true);
      setIsReasoning(false);

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        await streamMessage(
          { conversationId: currentConv.id, content },
          {
            onStart: (info) => {
              meta = { id: info.messageId, createdAt: info.createdAt };
            },
            onToken: (text) => {
              accumulated += text;
              setStreamingContent(accumulated);
              // First answer token: swap the spinner for real text.
              setIsLoading(false);
              setIsReasoning(false);
            },
            onReasoning: () => {
              // The text itself is not shown — only that thinking is happening.
              // Keeps the UI honest during a long pre-answer pause.
              setIsReasoning(true);
            },
            onError: (message) => {
              setError(message);
            },
          },
          controller.signal
        );
      } catch (err) {
        // An abort is the user pressing Stop, not a failure. Whatever text
        // already arrived is kept.
        const aborted =
          err instanceof DOMException && err.name === "AbortError";
        if (!aborted) {
          setError(
            err instanceof Error
              ? `Could not reach the server: ${err.message}`
              : "Could not reach the server."
          );
        }
      } finally {
        // Runs on success, error, and abort alike — so a partial reply is
        // never lost and the composer is never left disabled.
        const text = accumulated;
        if (text) {
          setMessages((prev) => [
            ...prev,
            {
              id: meta?.id ?? crypto.randomUUID(),
              role: "assistant",
              content: text,
              createdAt: meta?.createdAt ?? new Date().toISOString(),
            },
          ]);
        }
        setStreamingContent(null);
        setIsLoading(false);
        setIsStreaming(false);
        setIsReasoning(false);
        abortRef.current = null;
      }
    },
    [conversation, isStreaming]
  );

  return {
    messages,
    streamingContent,
    conversation,
    isLoading,
    isStreaming,
    isReasoning,
    error,
    submit,
    stop,
    startNewConversation,
  };
}
