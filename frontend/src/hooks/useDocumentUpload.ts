"use client";

import { useState, useCallback, useRef } from "react";
import type { UploadedDocument } from "@/types";
import { uploadDocument } from "@/services/documents";

interface UseDocumentUploadReturn {
  documents: UploadedDocument[];
  isDragOver: boolean;
  isUploading: boolean;
  uploadError: string | null;
  handleDrop: (e: React.DragEvent) => void;
  handleDragOver: (e: React.DragEvent) => void;
  handleDragLeave: () => void;
  handleFileSelect: (files: FileList | null) => void;
  clearError: () => void;
  inputRef: React.RefObject<HTMLInputElement | null>;
}

const ACCEPTED_TYPES = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "text/plain",
  "text/markdown",
];

export function useDocumentUpload(
  initialDocs: UploadedDocument[] = []
): UseDocumentUploadReturn {
  const [documents, setDocuments] = useState<UploadedDocument[]>(initialDocs);
  const [isDragOver, setIsDragOver] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const processFiles = useCallback(async (files: File[]) => {
    const validFiles = files.filter((f) => ACCEPTED_TYPES.includes(f.type));
    if (validFiles.length === 0) {
      setUploadError("Unsupported file type. Upload PDF, DOCX, TXT, or MD files.");
      return;
    }

    setIsUploading(true);
    setUploadError(null);

    for (const file of validFiles) {
      try {
        const doc = await uploadDocument(file);
        setDocuments((prev) => [doc, ...prev]);
      } catch {
        setUploadError(`Failed to upload "${file.name}". Please try again.`);
      }
    }

    setIsUploading(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragOver(false);
      const files = Array.from(e.dataTransfer.files);
      void processFiles(files);
    },
    [processFiles]
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setIsDragOver(false);
  }, []);

  const handleFileSelect = useCallback(
    (fileList: FileList | null) => {
      if (!fileList) return;
      void processFiles(Array.from(fileList));
    },
    [processFiles]
  );

  const clearError = useCallback(() => setUploadError(null), []);

  return {
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
  };
}
