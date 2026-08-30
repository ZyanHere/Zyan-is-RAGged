"use client";

import { useState, useCallback } from "react";
import type { Message, Conversation } from "@/types";
import { sendMessage, createConversation } from "@/services/chat";

interface UseChatReturn {
  messages: Message[];
  conversation: Conversation | null;
  isLoading: boolean;
  error: string | null;
  submit: (content: string) => Promise<void>;
  startNewConversation: () => void;
}

export function useChat(): UseChatReturn {
  const [messages, setMessages] = useState<Message[]>([]);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const startNewConversation = useCallback(() => {
    setMessages([]);
    setConversation(null);
    setError(null);
  }, []);

  const submit = useCallback(
    async (content: string) => {
      if (!content.trim() || isLoading) return;
      setError(null);

      // Create conversation on first message
      let currentConv = conversation;
      if (!currentConv) {
        try {
          currentConv = await createConversation(content.slice(0, 60));
          setConversation(currentConv);
        } catch {
          setError("Failed to start conversation. Please try again.");
          return;
        }
      }

      // Optimistically add user message
      const userMessage: Message = {
        id: crypto.randomUUID(),
        role: "user",
        content,
        createdAt: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, userMessage]);
      setIsLoading(true);

      try {
        const assistantMessage = await sendMessage({
          conversationId: currentConv.id,
          content,
        });
        setMessages((prev) => [...prev, assistantMessage]);
      } catch {
        setError("Failed to get a response. Please try again.");
        // Remove the optimistic user message on failure
        setMessages((prev) => prev.filter((m) => m.id !== userMessage.id));
      } finally {
        setIsLoading(false);
      }
    },
    [conversation, isLoading]
  );

  return { messages, conversation, isLoading, error, submit, startNewConversation };
}
