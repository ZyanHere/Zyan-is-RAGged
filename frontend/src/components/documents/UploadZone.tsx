"use client";

import { useRef } from "react";
import { cn } from "@/lib/utils";
import { formatFileSize } from "@/services/documents";
import { DocumentStatusBadge } from "./DocumentStatusBadge";
import type { UploadedDocument } from "@/types";

interface UploadZoneProps {
  documents: UploadedDocument[];
  isDragOver: boolean;
  isUploading: boolean;
  uploadError: string | null;
  onDrop: (e: React.DragEvent) => void;
  onDragOver: (e: React.DragEvent) => void;
  onDragLeave: () => void;
  onFileSelect: (files: FileList | null) => void;
  onClearError: () => void;
  inputRef: React.RefObject<HTMLInputElement | null>;
}

export function UploadZone({
  documents,
  isDragOver,
  isUploading,
  uploadError,
  onDrop,
  onDragOver,
  onDragLeave,
  onFileSelect,
  onClearError,
  inputRef,
}: UploadZoneProps) {
  return (
    <div className="flex flex-col gap-3">
      {/* Drop zone */}
      <div
        onDrop={onDrop}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onClick={() => inputRef.current?.click()}
        className={cn(
          "flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-4 py-6 text-center cursor-pointer transition-all select-none",
          isDragOver
            ? "border-blue-400 bg-blue-50"
            : "border-neutral-200 bg-neutral-50 hover:border-blue-300 hover:bg-blue-50/50"
        )}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".pdf,.docx,.txt,.md"
          className="sr-only"
          onChange={(e) => onFileSelect(e.target.files)}
        />

        {isUploading ? (
          <>
            <svg className="h-6 w-6 text-blue-500 animate-bounce" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M17 8l-5-5-5 5M12 3v12" />
            </svg>
            <span className="text-xs text-blue-600 font-medium">Uploading…</span>
          </>
        ) : (
          <>
            <svg className="h-6 w-6 text-neutral-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M17 8l-5-5-5 5M12 3v12" />
            </svg>
            <div>
              <p className="text-xs font-medium text-neutral-600">
                {isDragOver ? "Drop to upload" : "Drop files or click"}
              </p>
              <p className="text-xs text-neutral-400">PDF, DOCX, TXT, MD</p>
            </div>
          </>
        )}
      </div>

      {/* Upload error */}
      {uploadError && (
        <div className="flex items-start justify-between gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          <span>{uploadError}</span>
          <button onClick={onClearError} className="flex-shrink-0 text-red-400 hover:text-red-600">✕</button>
        </div>
      )}

      {/* Document list */}
      {documents.length > 0 && (
        <div className="flex flex-col gap-1.5">
          {documents.map((doc) => (
            <div
              key={doc.id}
              className="flex items-center justify-between gap-2 rounded-lg border border-neutral-200 bg-white px-3 py-2"
            >
              <div className="flex items-center gap-2 min-w-0">
                <svg className="h-4 w-4 flex-shrink-0 text-neutral-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
                  <polyline points="14 2 14 8 20 8" />
                </svg>
                <div className="min-w-0">
                  <p className="truncate text-xs font-medium text-neutral-700">{doc.name}</p>
                  <p className="text-xs text-neutral-400">{formatFileSize(doc.size)}</p>
                </div>
              </div>
              <DocumentStatusBadge status={doc.status} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
