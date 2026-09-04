/**
 * chat.ts — Chat service
 *
 * All chat-related API calls live here.
 */

import { apiClient } from "./api";
import { parseSseStream } from "@/lib/sse";
import type { Conversation, SendMessageRequest } from "@/types";

/**
 * Conversations are not persisted yet — the backend keeps history in memory,
 * keyed by an id the client generates. Listing them needs a database, which
 * arrives with the persistence work.
 */
export async function getConversations(): Promise<Conversation[]> {
  return [];
}

/**
 * Mints a conversation locally. The generated id is what we send to
 * /api/chat; the backend keys its in-memory history by it, which is enough
 * for multi-turn chat until conversations are stored properly.
 */
export async function createConversation(title?: string): Promise<Conversation> {
  return {
    id: crypto.randomUUID(),
    title: title ?? "New conversation",
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    messageCount: 0,
  };
}

export interface StreamHandlers {
  /** Fired once, before any text. Carries the id the server assigned. */
  onStart?: (info: { messageId: string; createdAt: string }) => void;
  /** Fired for each piece of answer text. Append, do not replace. */
  onToken: (text: string) => void;
  /**
   * Fired while a reasoning model is thinking out loud. This is not part of
   * the answer — without it the UI would sit silent for many seconds and look
   * hung, because reasoning models emit no answer text until they finish.
   */
  onReasoning?: (text: string) => void;
  /** The server reported a failure — possibly after some text already arrived. */
  onError?: (message: string, retryable: boolean) => void;
  /** Generation finished normally. */
  onDone?: () => void;
}

/**
 * Send a message and stream the reply.
 *
 * Resolves when the stream ends. Rejects with an AbortError if `signal` is
 * aborted — callers should treat that as "the user pressed Stop", not a failure.
 */
export async function streamMessage(
  req: SendMessageRequest,
  handlers: StreamHandlers,
  signal?: AbortSignal
): Promise<void> {
  const body = await apiClient.postStream("/api/chat", req, signal);

  for await (const event of parseSseStream(body)) {
    let data: Record<string, unknown> = {};
    try {
      data = JSON.parse(event.data) as Record<string, unknown>;
    } catch {
      // A malformed payload should not kill the whole stream.
      continue;
    }

    switch (event.event) {
      case "start":
        handlers.onStart?.({
          messageId: String(data.messageId ?? crypto.randomUUID()),
          createdAt: String(data.createdAt ?? new Date().toISOString()),
        });
        break;
      case "token":
        if (typeof data.text === "string") handlers.onToken(data.text);
        break;
      case "reasoning":
        if (typeof data.text === "string") handlers.onReasoning?.(data.text);
        break;
      case "error":
        handlers.onError?.(
          String(data.message ?? "The assistant failed to respond."),
          Boolean(data.retryable ?? true)
        );
        break;
      case "done":
        handlers.onDone?.();
        break;
    }
  }
}
