/**
 * api.ts — Base API client
 *
 * All HTTP calls go through here. The base URL is read from the environment,
 * never hardcoded. Swap the mock flag to false when the backend is ready.
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/** Set to true to use mock data instead of hitting the real backend */
export const MOCK_MODE = true;

class ApiClient {
  private baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl;
  }

  async get<T>(path: string): Promise<T> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      headers: { "Content-Type": "application/json" },
    });
    if (!res.ok) throw new Error(`GET ${path} failed: ${res.statusText}`);
    return res.json() as Promise<T>;
  }

  async post<T>(path: string, body: unknown): Promise<T> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`POST ${path} failed: ${res.statusText}`);
    return res.json() as Promise<T>;
  }

  async postFormData<T>(path: string, formData: FormData): Promise<T> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      method: "POST",
      body: formData,
    });
    if (!res.ok) throw new Error(`POST ${path} failed: ${res.statusText}`);
    return res.json() as Promise<T>;
  }
}

export const apiClient = new ApiClient(API_BASE_URL);
