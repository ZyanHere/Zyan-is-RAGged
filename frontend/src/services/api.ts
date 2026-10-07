/**
 * api.ts — the base HTTP client.
 *
 * Every HTTP call in the app goes through here, and the base URL comes from the
 * environment rather than a literal. `NEXT_PUBLIC_` is what makes the variable
 * available in the browser; without the prefix it would exist only on the
 * server and read as `undefined` here.
 *
 * The browser only ever talks to the backend on :8000. It never calls the agent
 * on :8001 — the agent has no CORS configuration precisely so that a direct
 * browser call fails loudly rather than quietly working and hiding a layering
 * violation.
 *
 * Two things this file exists to get right:
 *
 * **Error bodies are read, not discarded.** The backend and agent answer
 * failures with `{"detail": "..."}` and a real status code, and those messages
 * are the whole point of stage 1.1's fail-loudly design — "this PDF is
 * password-protected", "almost certainly a scanned document, nothing was
 * indexed". Throwing `res.statusText` would replace all of that with "Bad
 * Request".
 *
 * **Multipart uploads must not set Content-Type.** See `postForm`.
 */

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/**
 * A failed request, carrying the status so callers can distinguish *kinds* of
 * failure without string-matching a message.
 *
 * `status === 0` means the request never reached the server at all — wrong
 * port, backend not running, DNS failure. Worth separating, because "the
 * backend rejected your PDF" and "there is no backend" need different reactions
 * from whoever is looking at the screen.
 */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** Turn any thrown value into something worth showing a human. */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "Something went wrong.";
}

/**
 * Pull `detail` out of an error response, falling back to the status line.
 *
 * A 502 from a crashed proxy arrives as HTML, and a `.json()` call on it
 * throws — so the parse is guarded. Losing the status code because the body was
 * not JSON would be the worst of both outcomes.
 */
async function readDetail(res: Response): Promise<string> {
  try {
    const body: unknown = await res.json();
    if (body && typeof body === "object" && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === "string" && detail.trim().length > 0) {
        return detail;
      }
    }
  } catch {
    // Not JSON. Fall through to the status line.
  }
  return `${res.status} ${res.statusText || "Request failed"}`;
}

async function parse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    throw new ApiError(res.status, await readDetail(res));
  }
  return (await res.json()) as T;
}

/**
 * `fetch` rejects only when the request never completed — a connection refused,
 * a DNS failure, a CORS block. An HTTP 500 is a *successful* fetch with a bad
 * status, which is why `res.ok` has to be checked separately.
 */
function unreachable(cause: unknown): ApiError {
  const reason = cause instanceof Error ? cause.message : String(cause);
  return new ApiError(
    0,
    `Could not reach the backend at ${API_BASE_URL}. Is it running on that ` +
      `port? (${reason})`,
  );
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (cause) {
    throw unreachable(cause);
  }
  return parse<T>(res);
}

/**
 * POST a multipart form — used for file uploads.
 *
 * **No `Content-Type` header, deliberately.** A multipart body needs a header
 * like `multipart/form-data; boundary=----WebKitFormBoundaryAbc123`, where the
 * boundary is a random string the browser generates to separate the parts.
 * Setting the header by hand means sending it *without* a boundary, so the
 * server cannot find the field separators and rejects the body as malformed —
 * usually as a confusing 422 about a missing `file` field.
 *
 * Passing a `FormData` with no `Content-Type` lets the browser set the header
 * and its matching boundary together. This is the single most common file
 * upload bug, and the fix is to delete a line rather than add one.
 */
export async function postForm<T>(path: string, form: FormData): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      body: form,
    });
  } catch (cause) {
    throw unreachable(cause);
  }
  return parse<T>(res);
}
