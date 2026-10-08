/**
 * The store.
 *
 * ── Why `makeStore()` and not a module-level singleton ──────────────────────
 *
 * A singleton created at import time works in a browser-only app and breaks in
 * a server-rendered one: the module is evaluated once per server *process*, so
 * every request would share one store. One user's transcript could be rendered
 * into another user's HTML.
 *
 * Nothing in myRAG is server-rendered with user data today, so the bug is
 * latent rather than live. It is still the wrong default to establish — the
 * factory costs one function call, and the singleton version fails in a way
 * that is hard to see in testing and very visible in production.
 *
 * `providers.tsx` calls this once per client mount, so the browser still gets
 * exactly one store for the session.
 *
 * ── What lives here ─────────────────────────────────────────────────────────
 *
 * The API slice holds the RTK Query cache — server state — in the same store
 * that will hold client state. That is the reason for choosing RTK Query over
 * TanStack Query: one store, one DevTools timeline, one mental model.
 *
 * The three kinds of state, kept deliberately separate:
 *
 *   state.api      server state — the RTK Query cache
 *   state.chat     client/domain state — the transcript
 *   state.uploads  client/domain state — what this session uploaded
 *   state.ui       UI state — application chrome
 *
 * Anything that changes at interaction rate (a composer's text, a scroll
 * position) is in none of them: it stays local to its component.
 */

import { configureStore } from "@reduxjs/toolkit";

import { chatSlice } from "@/features/chat/chatSlice";
import { uploadsSlice } from "@/features/documents/uploadsSlice";
import { uiSlice } from "@/features/ui/uiSlice";
import { baseApi } from "@/services/baseApi";

export function makeStore() {
  return configureStore({
    reducer: {
      // ── Server state ────────────────────────────────────────────────────
      //
      // `reducerPath` is "api", so the cache lives at `state.api`. Using the
      // slice's own property rather than a literal means renaming it is a
      // one-line change that cannot go half-done.
      [baseApi.reducerPath]: baseApi.reducer,

      // ── Client state ────────────────────────────────────────────────────
      //
      // Mounted under each slice's own `reducerPath` for a load-bearing
      // reason: `createSlice({ selectors })` generates selectors that assume
      // the slice lives at that key. Writing "chat" as a literal here would
      // work until someone renamed the slice, at which point every selector
      // would silently read `undefined`.
      [chatSlice.reducerPath]: chatSlice.reducer,
      [uploadsSlice.reducerPath]: uploadsSlice.reducer,
      [uiSlice.reducerPath]: uiSlice.reducer,
    },

    /**
     * RTK Query's middleware manages cache lifetime, polling, deduplication of
     * concurrent identical requests, and tag invalidation.
     *
     * **Forgetting this is the classic RTK Query mistake**, because nothing
     * fails loudly: the endpoints still typecheck, the hooks still render, and
     * no request is ever made. Adding it in the same commit as the reducer is
     * the only reliable defence.
     */
    middleware: (getDefaultMiddleware) =>
      getDefaultMiddleware().concat(baseApi.middleware),
  });
}

/**
 * The store's own types, derived from the factory rather than declared.
 *
 * Writing `RootState` by hand would let it drift from the real reducer map,
 * and a selector would then typecheck against state that does not exist.
 * Inferring it means adding a slice updates every selector's type for free.
 */
export type AppStore = ReturnType<typeof makeStore>;
export type RootState = ReturnType<AppStore["getState"]>;
export type AppDispatch = AppStore["dispatch"];
