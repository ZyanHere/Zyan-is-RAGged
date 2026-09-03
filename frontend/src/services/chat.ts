/**
 * chat.ts — Chat service
 *
 * All chat-related API calls live here.
 */

import { apiClient } from "./api";
import type { Conversation, Message, SendMessageRequest } from "@/types";

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

export async function sendMessage(req: SendMessageRequest): Promise<Message> {
  const res = await apiClient.post<{ message: Message }>("/api/chat", req);
  return res.message;
}
