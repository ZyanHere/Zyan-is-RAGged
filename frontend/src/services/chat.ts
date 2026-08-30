/**
 * chat.ts — Chat service
 *
 * All chat-related API calls live here.
 * Currently returns mock data (MOCK_MODE = true in api.ts).
 * To connect to the real backend: replace each mock branch with an apiClient call.
 */

import { apiClient, MOCK_MODE } from "./api";
import type { Conversation, Message, SendMessageRequest } from "@/types";

// ── Mock data ─────────────────────────────────────────────────────────────────

const MOCK_CONVERSATIONS: Conversation[] = [
  {
    id: "conv-1",
    title: "What is retrieval-augmented generation?",
    createdAt: new Date(Date.now() - 86400000).toISOString(),
    updatedAt: new Date(Date.now() - 3600000).toISOString(),
    messageCount: 4,
  },
  {
    id: "conv-2",
    title: "Summarise the Q3 financial report",
    createdAt: new Date(Date.now() - 172800000).toISOString(),
    updatedAt: new Date(Date.now() - 172800000).toISOString(),
    messageCount: 2,
  },
];

const MOCK_ASSISTANT_REPLY = (userContent: string): Message => ({
  id: crypto.randomUUID(),
  role: "assistant",
  content:
    `This is a mock response to: "${userContent}"\n\n` +
    `The RAG engine is not yet connected. Once the backend is wired up, ` +
    `this response will contain a grounded answer with citations from your uploaded documents.`,
  citations: [
    {
      id: "cit-1",
      documentId: "doc-1",
      documentTitle: "example-document.pdf",
      excerpt: "This is a placeholder citation excerpt from a retrieved chunk.",
      pageNumber: 3,
    },
  ],
  createdAt: new Date().toISOString(),
});

// ── Service functions ─────────────────────────────────────────────────────────

export async function getConversations(): Promise<Conversation[]> {
  if (MOCK_MODE) {
    await delay(300);
    return MOCK_CONVERSATIONS;
  }
  return apiClient.get<Conversation[]>("/api/conversations");
}

export async function getMessages(conversationId: string): Promise<Message[]> {
  if (MOCK_MODE) {
    await delay(200);
    return [];
  }
  return apiClient.get<Message[]>(`/api/conversations/${conversationId}/messages`);
}

export async function sendMessage(req: SendMessageRequest): Promise<Message> {
  if (MOCK_MODE) {
    await delay(800); // simulate network + model latency
    return MOCK_ASSISTANT_REPLY(req.content);
  }
  const res = await apiClient.post<{ message: Message }>("/api/chat", req);
  return res.message;
}

export async function createConversation(title?: string): Promise<Conversation> {
  if (MOCK_MODE) {
    await delay(200);
    return {
      id: crypto.randomUUID(),
      title: title ?? "New conversation",
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      messageCount: 0,
    };
  }
  return apiClient.post<Conversation>("/api/conversations", { title });
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function delay(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
