import axios from "axios";

export const api = axios.create({
  baseURL: "/api",
  timeout: 60_000,
});

export type DocStatus = "pending" | "processing" | "done" | "failed";

export interface DocumentSummary {
  id: number;
  filename: string;
  uploaded_at: string;
  status: DocStatus;
  category: string | null;
  category_confidence: number | null;
  summary: string | null;
  size_bytes: number;
  error: string | null;
}

export interface DocumentDetail extends DocumentSummary {
  extracted_fields: Record<string, unknown> | null;
  raw_text: string | null;
  token_count: number | null;
  mime_type: string;
}

export interface DocumentList {
  items: DocumentSummary[];
  total: number;
}

export interface SearchHit {
  document_id: number;
  filename: string;
  category: string | null;
  snippet: string;
  score: number;
}

export interface SearchResponse {
  query: string;
  hits: SearchHit[];
}

export interface AnalyticsResponse {
  total_documents: number;
  processed: number;
  failed: number;
  pending: number;
  by_category: { category: string; count: number }[];
  recent: DocumentSummary[];
}

export const uploadDocument = async (file: File): Promise<DocumentDetail> => {
  const form = new FormData();
  form.append("file", file);
  const { data } = await api.post<DocumentDetail>("/documents", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
};

export const listDocuments = async (params: {
  category?: string;
  status?: string;
  q?: string;
  limit?: number;
  offset?: number;
} = {}): Promise<DocumentList> => {
  const { data } = await api.get<DocumentList>("/documents", { params });
  return data;
};

export const getDocument = async (id: number): Promise<DocumentDetail> => {
  const { data } = await api.get<DocumentDetail>(`/documents/${id}`);
  return data;
};

export const reprocessDocument = async (id: number): Promise<DocumentDetail> => {
  const { data } = await api.post<DocumentDetail>(`/documents/${id}/reprocess`);
  return data;
};

export const deleteDocument = async (id: number): Promise<void> => {
  await api.delete(`/documents/${id}`);
};

export const searchDocuments = async (q: string, top_k = 10): Promise<SearchResponse> => {
  const { data } = await api.get<SearchResponse>("/search", { params: { q, top_k } });
  return data;
};

export const getAnalytics = async (): Promise<AnalyticsResponse> => {
  const { data } = await api.get<AnalyticsResponse>("/analytics");
  return data;
};
