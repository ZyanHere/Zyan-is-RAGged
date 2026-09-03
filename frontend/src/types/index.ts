// ─── Core domain types for myRAG ─────────────────────────────────────────────

// ── Chat ─────────────────────────────────────────────────────────────────────

export type MessageRole = "user" | "assistant";

export interface Citation {
  id: string;
  documentId: string;
  documentTitle: string;
  excerpt: string;
  pageNumber?: number;
  chunkIndex?: number;
}

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  citations?: Citation[];
  createdAt: string;
  /** Only relevant for assistant messages */
  isStreaming?: boolean;
}

export interface Conversation {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messageCount: number;
}

// ── API ───────────────────────────────────────────────────────────────────────

export interface SendMessageRequest {
  conversationId: string;
  content: string;
}

export interface SendMessageResponse {
  message: Message;
}

export interface ApiError {
  message: string;
  code?: string;
}
