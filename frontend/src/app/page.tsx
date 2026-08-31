"use client";

import { useState, useEffect } from "react";
import { Sidebar } from "@/components/layout/Sidebar";
import { ChatWindow } from "@/components/chat/ChatWindow";
import { ChatInput } from "@/components/chat/ChatInput";
import { useChat } from "@/hooks/useChat";
import { getConversations } from "@/services/chat";
import { MOCK_MODE } from "@/services/api";
import type { Conversation } from "@/types";

export default function ChatPage() {
  const { messages, conversation, isLoading, error, submit, startNewConversation } = useChat();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [conversations, setConversations] = useState<Conversation[]>([]);

  // Load conversation list on mount
  useEffect(() => {
    getConversations().then(setConversations).catch(console.error);
  }, []);

  // When a new conversation is created, add it to the sidebar list
  useEffect(() => {
    if (conversation && !conversations.find((c) => c.id === conversation.id)) {
      setConversations((prev) => [conversation, ...prev]);
    }
  }, [conversation, conversations]);

  const handleSubmit = async (content: string) => {
    await submit(content);
  };

  const handleNewChat = () => {
    startNewConversation();
    setSidebarOpen(false);
  };

  return (
    <div className="flex h-dvh overflow-hidden bg-white">
      {/* Sidebar */}
      <Sidebar
        conversations={conversations}
        activeConversationId={conversation?.id ?? null}
        onNewChat={handleNewChat}
        onSelectConversation={(id) => {
          // TODO: load existing conversation messages when backend is ready
          setSidebarOpen(false);
          console.log("Select conversation:", id);
        }}
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />

      {/* Main chat area */}
      <div className="flex flex-1 flex-col min-w-0">
        {/* Top bar */}
        <header className="flex items-center gap-3 border-b border-neutral-200 px-4 py-3">
          {/* Mobile menu toggle */}
          <button
            onClick={() => setSidebarOpen(true)}
            className="lg:hidden text-neutral-400 hover:text-neutral-700"
            aria-label="Open sidebar"
          >
            <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="3" y1="12" x2="21" y2="12" />
              <line x1="3" y1="6" x2="21" y2="6" />
              <line x1="3" y1="18" x2="21" y2="18" />
            </svg>
          </button>

          <div className="flex items-center gap-2">
            {conversation ? (
              <h1 className="text-sm font-medium text-neutral-700 truncate">
                {conversation.title}
              </h1>
            ) : (
              <h1 className="text-sm font-medium text-neutral-500">myRAG</h1>
            )}
          </div>

          {/* Connection status pill */}
          {MOCK_MODE ? (
            <div className="ml-auto flex items-center gap-1.5 rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-xs text-amber-700">
              <span className="h-1.5 w-1.5 rounded-full bg-amber-400 animate-pulse" />
              Mock mode
            </div>
          ) : (
            <div className="ml-auto flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs text-emerald-700">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
              Live
            </div>
          )}
        </header>

        {/* Chat window */}
        <ChatWindow
          messages={messages}
          isLoading={isLoading}
          error={error}
          onPromptClick={handleSubmit}
        />

        {/* Input area */}
        <div className="border-t border-neutral-100 bg-white px-4 py-4">
          <div className="mx-auto max-w-2xl">
            <ChatInput
              onSubmit={handleSubmit}
              isLoading={isLoading}
            />
            <p className="mt-2 text-center text-xs text-neutral-400">
              myRAG can make mistakes. Verify important information.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
