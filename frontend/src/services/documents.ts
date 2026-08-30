/**
 * documents.ts — Document service
 *
 * Handles document upload and status polling.
 * Returns mock data while MOCK_MODE is true.
 */

import { apiClient, MOCK_MODE } from "./api";
import type { UploadedDocument, DocumentStatus } from "@/types";

// ── Mock data ─────────────────────────────────────────────────────────────────

const MOCK_DOCUMENTS: UploadedDocument[] = [
  {
    id: "doc-1",
    name: "example-document.pdf",
    size: 2_340_000,
    mimeType: "application/pdf",
    status: "ready",
    uploadedAt: new Date(Date.now() - 3600000).toISOString(),
    processedAt: new Date(Date.now() - 3500000).toISOString(),
  },
  {
    id: "doc-2",
    name: "technical-spec.docx",
    size: 875_000,
    mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    status: "processing",
    uploadedAt: new Date(Date.now() - 120000).toISOString(),
  },
];

// ── Service functions ─────────────────────────────────────────────────────────

export async function getDocuments(): Promise<UploadedDocument[]> {
  if (MOCK_MODE) {
    await delay(300);
    return MOCK_DOCUMENTS;
  }
  return apiClient.get<UploadedDocument[]>("/api/documents");
}

export async function uploadDocument(file: File): Promise<UploadedDocument> {
  if (MOCK_MODE) {
    await delay(600);
    return {
      id: crypto.randomUUID(),
      name: file.name,
      size: file.size,
      mimeType: file.type,
      status: "processing" as DocumentStatus,
      uploadedAt: new Date().toISOString(),
    };
  }
  const formData = new FormData();
  formData.append("file", file);
  return apiClient.postFormData<UploadedDocument>("/api/documents", formData);
}

export async function getDocumentStatus(documentId: string): Promise<UploadedDocument> {
  if (MOCK_MODE) {
    await delay(200);
    const doc = MOCK_DOCUMENTS.find((d) => d.id === documentId);
    if (!doc) throw new Error(`Document not found: ${documentId}`);
    return doc;
  }
  return apiClient.get<UploadedDocument>(`/api/documents/${documentId}`);
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function delay(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
