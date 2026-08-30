"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { UploadZone } from "@/components/documents/UploadZone";
import { useDocumentUpload } from "@/hooks/useDocumentUpload";
import { getDocuments } from "@/services/documents";
import type { Conversation, UploadedDocument } from "@/types";

interface SidebarProps {
  conversations: Conversation[];
  activeConversationId: string | null;
  onNewChat: () => void;
  onSelectConversation: (id: string) => void;
  isOpen: boolean;
  onClose: () => void;
}

export function Sidebar({
  conversations,
  activeConversationId,
  onNewChat,
  onSelectConversation,
  isOpen,
  onClose,
}: SidebarProps) {
  const [initialDocs, setInitialDocs] = useState<UploadedDocument[]>([]);

  useEffect(() => {
    getDocuments().then(setInitialDocs).catch(console.error);
  }, []);

  const {
    documents,
    isDragOver,
    isUploading,
    uploadError,
    handleDrop,
    handleDragOver,
    handleDragLeave,
    handleFileSelect,
    clearError,
    inputRef,
  } = useDocumentUpload(initialDocs);

  return (
    <>
      {/* Mobile overlay */}
      {isOpen && (
        <div
          className="fixed inset-0 z-20 bg-black/30 lg:hidden"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      {/* Sidebar panel */}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-30 flex w-72 flex-col border-r border-neutral-200 bg-neutral-50 transition-transform duration-200",
          "lg:static lg:translate-x-0",
          isOpen ? "translate-x-0" : "-translate-x-full"
        )}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-4 border-b border-neutral-200">
          <div className="flex items-center gap-2">
            <div className="h-7 w-7 rounded-lg bg-gradient-to-br from-blue-500 to-violet-600 flex items-center justify-center">
              <span className="text-xs font-bold text-white">R</span>
            </div>
            <span className="font-semibold text-neutral-800 tracking-tight">myRAG</span>
          </div>
          <button
            onClick={onClose}
            className="lg:hidden text-neutral-400 hover:text-neutral-600"
            aria-label="Close sidebar"
          >
            <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {/* New chat button */}
        <div className="px-3 py-3">
          <button
            onClick={onNewChat}
            className="flex w-full items-center gap-2 rounded-xl border border-neutral-200 bg-white px-3 py-2.5 text-sm font-medium text-neutral-700 hover:bg-blue-50 hover:border-blue-300 hover:text-blue-700 transition-all shadow-sm"
          >
            <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
            New chat
          </button>
        </div>

        {/* Scrollable content */}
        <div className="flex-1 overflow-y-auto px-3 py-2 flex flex-col gap-4">
          {/* Conversations */}
          {conversations.length > 0 && (
            <div>
              <p className="mb-1.5 px-1 text-xs font-medium uppercase tracking-wide text-neutral-400">
                Recent
              </p>
              <nav className="flex flex-col gap-0.5">
                {conversations.map((conv) => (
                  <button
                    key={conv.id}
                    onClick={() => onSelectConversation(conv.id)}
                    className={cn(
                      "w-full rounded-lg px-3 py-2 text-left text-sm transition-all",
                      conv.id === activeConversationId
                        ? "bg-blue-100 text-blue-800 font-medium"
                        : "text-neutral-600 hover:bg-neutral-200/70"
                    )}
                  >
                    <p className="truncate">{conv.title}</p>
                  </button>
                ))}
              </nav>
            </div>
          )}

          {/* Documents */}
          <div>
            <p className="mb-1.5 px-1 text-xs font-medium uppercase tracking-wide text-neutral-400">
              Documents
            </p>
            <UploadZone
              documents={documents}
              isDragOver={isDragOver}
              isUploading={isUploading}
              uploadError={uploadError}
              onDrop={handleDrop}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onFileSelect={handleFileSelect}
              onClearError={clearError}
              inputRef={inputRef}
            />
          </div>
        </div>

        {/* Footer */}
        <div className="border-t border-neutral-200 px-4 py-3">
          <p className="text-xs text-neutral-400 text-center">
            Mock mode — backend not connected
          </p>
        </div>
      </aside>
    </>
  );
}
