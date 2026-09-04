/**
 * api.ts — Base API client
 *
 * Every HTTP call goes through here. The base URL comes from the environment,
 * never hardcoded.
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

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

  /**
   * POST and return the raw response body for streaming.
   *
   * `signal` comes from an AbortController — aborting it closes the connection,
   * which is what makes the Stop button actually stop generation rather than
   * just hiding the output.
   */
  async postStream(
    path: string,
    body: unknown,
    signal?: AbortSignal
  ): Promise<ReadableStream<Uint8Array>> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify(body),
      signal,
    });

    if (!res.ok) throw new Error(`POST ${path} failed: ${res.status} ${res.statusText}`);
    if (!res.body) throw new Error(`POST ${path} returned no body to stream`);

    return res.body;
  }
}

export const apiClient = new ApiClient(API_BASE_URL);
