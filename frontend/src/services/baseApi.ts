/**
 * The API slice.
 *
 * One `createApi` for the whole app. Endpoints are added by feature in
 * `documentsApi.ts` and `queryApi.ts` via `injectEndpoints`, rather than all
 * being declared here — that keeps each feature's requests next to the feature
 * and stops this file growing into a list of everything the app can do.
 *
 * The browser only ever talks to the backend on :8000. It never calls the
 * agent on :8001 — the agent has no CORS configuration precisely so that a
 * direct browser call fails loudly instead of quietly working and hiding a
 * layering violation.
 */

import {
  createApi,
  fetchBaseQuery,
  type BaseQueryFn,
  type FetchArgs,
  type FetchBaseQueryError,
} from "@reduxjs/toolkit/query/react";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/**
 * A failure, normalised into something a component can render.
 *
 * `fetchBaseQuery` reports errors as `{ status, data }` where `status` is
 * either an HTTP code or one of several string tags, and `data` is whatever
 * the server sent — so every component would otherwise have to narrow a union
 * and dig for a message. Normalising once, here, means `error.message` is
 * always a string worth showing.
 *
 * `status` is `null` when the request never reached the server at all. That
 * distinction matters: "the backend rejected your PDF" and "there is no
 * backend" need different reactions from whoever is looking at the screen.
 */
export interface ApiFailure {
  status: number | null;
  message: string;
}

/**
 * Pull `detail` out of an error body, falling back to the status line.
 *
 * The backend and agent answer failures with `{"detail": "..."}` and a real
 * status code, and those messages are the whole point of stage 1.1's
 * fail-loudly design — "this PDF is password-protected", "almost certainly a
 * scanned document, nothing was indexed". Discarding them for a bare "400"
 * would undo that work at the last step.
 */
function detailOf(data: unknown, fallback: string): string {
  if (data && typeof data === "object" && "detail" in data) {
    const detail = (data as { detail: unknown }).detail;
    if (typeof detail === "string" && detail.trim().length > 0) {
      return detail;
    }
  }
  return fallback;
}

function normalise(error: FetchBaseQueryError): ApiFailure {
  // An HTTP response with a non-2xx code. The server answered; read it.
  if (typeof error.status === "number") {
    return {
      status: error.status,
      message: detailOf(error.data, `Request failed (${error.status}).`),
    };
  }

  switch (error.status) {
    case "FETCH_ERROR":
      // Connection refused, DNS failure, CORS block — no response at all.
      return {
        status: null,
        message:
          `Could not reach the backend at ${API_BASE_URL}. Is it running on ` +
          `that port?`,
      };
    case "TIMEOUT_ERROR":
      return {
        status: null,
        message:
          "The backend did not respond in time. Ingestion is synchronous at " +
          "this stage, so a large PDF can exceed the timeout — it may still " +
          "be indexing.",
      };
    case "PARSING_ERROR":
      // A 2xx whose body was not JSON. Usually a proxy error page.
      return {
        status: error.originalStatus,
        message: `The backend returned a non-JSON response (${error.originalStatus}).`,
      };
    default:
      return { status: null, message: "Something went wrong." };
  }
}

const rawBaseQuery = fetchBaseQuery({
  baseUrl: API_BASE_URL,

  // Note what is *not* here: no `Content-Type` header.
  //
  // `fetchBaseQuery` sets `application/json` for a plain object body and
  // deliberately leaves the header alone for `FormData`. That second part is
  // load-bearing: a multipart body needs a header carrying a random boundary
  // string the browser generates, and setting the header by hand means sending
  // it without one. The server then cannot find the field separators and
  // rejects the body — typically as a confusing 422 about a missing `file`
  // field. The upload works because this header is absent.
});

const baseQueryWithMessages: BaseQueryFn<
  string | FetchArgs,
  unknown,
  ApiFailure
> = async (args, api, extraOptions) => {
  const result = await rawBaseQuery(args, api, extraOptions);

  if (result.error) {
    return { error: normalise(result.error) };
  }
  return result;
};

export const baseApi = createApi({
  reducerPath: "api",
  baseQuery: baseQueryWithMessages,

  // Declared now, used at stage 1.2.
  //
  // A tag is a label on cached data. A query declares what it `provides`, a
  // mutation declares what it `invalidates`, and RTK Query refetches the
  // overlap automatically. Today nothing provides `Document` because there is
  // no `GET /documents` to cache — the backend has no database to list from.
  //
  // The upload mutation still declares `invalidatesTags: ["Document"]`, which
  // is a no-op against an empty cache. When the list endpoint arrives at 1.2,
  // refetch-after-upload is already wired and needs no new code. That is the
  // concrete payoff of this architecture, and it is one line.
  tagTypes: ["Document"],

  // No endpoints here. Features inject their own, so each lives beside the
  // code that uses it.
  endpoints: () => ({}),
});
