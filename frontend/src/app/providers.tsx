"use client";

import { useState, type ReactNode } from "react";
import { Provider } from "react-redux";

import { makeStore } from "@/store";

/**
 * The client boundary that owns the store.
 *
 * `layout.tsx` stays a Server Component and renders this around `{children}`.
 * The Next.js guidance is explicit about the shape: put providers in their own
 * `"use client"` file and wrap as deep in the tree as possible, rather than
 * marking the layout itself a client component — that would opt the entire
 * document out of server rendering for the sake of one context.
 *
 * ── Creating the store exactly once ─────────────────────────────────────────
 *
 * Three ways to hold it, two of them wrong:
 *
 *   const store = makeStore()      a new store on *every* render; all state
 *                                  resets whenever a parent re-renders
 *   const store = globalStore      one store per server *process*, shared
 *                                  across requests — one user's state can
 *                                  render into another user's HTML
 *   useState(makeStore)            created once per mount, in both environments
 *
 * `useState(makeStore)` passes the function as a *lazy initializer*: React
 * calls it on the first render and never again. Note the missing parentheses —
 * `useState(makeStore())` would build a store on every render and throw it
 * away, which looks identical and behaves completely differently.
 *
 * Redux's own Next.js guide reaches for `useRef` here instead. That works, but
 * React 19's `react-hooks/refs` rule forbids reading a ref during render, and
 * the rule is right: refs are an escape hatch for values that survive renders
 * without causing them, and reading one while rendering is the pattern that
 * makes concurrent rendering unsafe. `useState` with a lazy initializer is the
 * supported way to say "compute this once".
 *
 * Nothing in myRAG is server-rendered with user data today, so the singleton
 * bug would be latent rather than live. It is still the wrong default to
 * establish: it fails invisibly in testing and very visibly in production.
 */
export function Providers({ children }: { children: ReactNode }) {
  const [store] = useState(makeStore);

  return <Provider store={store}>{children}</Provider>;
}
