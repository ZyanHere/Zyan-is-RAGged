"use client";

import { useState, useEffect, useMemo } from "react";
import { Sidebar } from "@/components/layout/Sidebar";
import { ChatWindow } from "@/components/chat/ChatWindow";
import { ChatInput } from "@/components/chat/ChatInput";
import { useChat } from "@/hooks/useChat";
import { getConversations } from "@/services/chat";
import type { Conversation } from "@/types";

export default function ChatPage() {
  const {
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
  } = useChat();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [storedConversations, setStoredConversations] = useState<Conversation[]>([]);

  // Load conversation list on mount
  useEffect(() => {
    getConversations().then(setStoredConversations).catch(console.error);
  }, []);

  // The active conversation may not be stored yet (it is created client-side),
  // so derive the sidebar list rather than syncing it into state.
  const conversations = useMemo(() => {
    if (!conversation) return storedConversations;
    const known = storedConversations.some((c) => c.id === conversation.id);
    return known ? storedConversations : [conversation, ...storedConversations];
  }, [conversation, storedConversations]);

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


        </header>

        {/* Chat window */}
        <ChatWindow
          messages={messages}
          streamingContent={streamingContent}
          isLoading={isLoading}
          isReasoning={isReasoning}
          error={error}
          onPromptClick={handleSubmit}
        />

        {/* Input area */}
        <div className="border-t border-neutral-100 bg-white px-4 py-4">
          <div className="mx-auto max-w-2xl">
            <ChatInput
              onSubmit={handleSubmit}
              onStop={stop}
              isStreaming={isStreaming}
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
