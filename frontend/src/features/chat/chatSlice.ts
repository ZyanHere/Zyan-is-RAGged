/**
 * The transcript.
 *
 * Client-owned domain state: the question-and-answer history of this session.
 * The server knows nothing about it — stage 1.1 is stateless and single-turn,
 * so every question is answered from the documents alone with no history
 * attached. This slice exists so you can see what you asked a moment ago.
 *
 * ── How a turn gets in ──────────────────────────────────────────────────────
 *
 * Two paths, deliberately asymmetric:
 *
 *   user turn       an explicit `questionAsked` dispatch from the component.
 *                   It genuinely originates there — nothing in the API
 *                   produced it, and it must appear before the request so the
 *                   composer does not clear into silence.
 *
 *   assistant turn  only by reacting to `ask.matchFulfilled`. There is no
 *                   public action that adds one.
 *
 * That asymmetry is the design. An assistant message carries citations, and
 * **an answer with citations should not be constructible by hand** — the only
 * way one can exist is as the result of a real retrieval. The reducer is the
 * enforcement, not a convention a future component might forget.
 *
 * It is the same instinct as making `page` a required field on `Chunk` rather
 * than an optional one: encode the invariant in the type system and the state
 * machine, not in a comment.
 *
 * ── The cost, stated honestly ───────────────────────────────────────────────
 *
 * Reading `page.tsx` does not tell you where the answer goes. The handler
 * dispatches a question and triggers a mutation, and the transcript updates
 * somewhere else. That indirection is real, and in a large codebase
 * "where did this state come from?" is a genuine cost. Redux DevTools shows
 * the action either way, which blunts it but does not remove it.
 *
 * The explicit alternative — `await ask(q).unwrap()` then
 * `dispatch(messageAdded(answer))` — reads top to bottom in one place. Both
 * are idiomatic RTK. This one was chosen for the invariant.
 */

import { createSlice, nanoid, type PayloadAction } from "@reduxjs/toolkit";

import { queryApi } from "@/services/queryApi";
import type { Message } from "@/types";

interface ChatState {
  messages: Message[];
}

const initialState: ChatState = {
  messages: [],
};

export const chatSlice = createSlice({
  name: "chat",
  initialState,

  reducers: {
    /**
     * Record the user's turn, before the request goes out.
     *
     * The `prepare` callback is why this reducer stays pure. `nanoid()` and
     * `Date.now()` are both non-deterministic, and calling either *inside* a
     * reducer would mean replaying the same action twice produces different
     * state — which breaks time-travel debugging and any future state replay.
     *
     * `prepare` runs in the action creator, outside the reducer, so the
     * randomness is baked into the action itself. The reducer then does
     * nothing but append what it was handed. This is exactly what `prepare`
     * exists for, and it is the standard answer to "where do I generate ids?".
     */
    questionAsked: {
      reducer(state, action: PayloadAction<Message>) {
        state.messages.push(action.payload);
      },
      prepare(question: string) {
        return {
          payload: {
            id: nanoid(),
            role: "user",
            content: question,
            createdAt: Date.now(),
          } satisfies Message,
        };
      },
    },
  },

  extraReducers: (builder) => {
    /**
     * The assistant's turn, appended when a query succeeds.
     *
     * `matchFulfilled` is a predicate RTK Query generates per endpoint. Every
     * endpoint shares the action type `api/executeMutation/fulfilled`, with
     * the endpoint name in `action.meta.arg.endpointName` — the matcher checks
     * that nested field, so this reducer sees only `ask` results and not
     * uploads.
     *
     * `action.payload` is already an `Answer`: `transformResponse` ran before
     * the value entered the cache, so the citations-into-sources merge is done
     * and this slice never sees a wire shape.
     *
     * Both of the values a reducer must not invent come from the action's
     * metadata rather than from `Date.now()` or `nanoid()`:
     *
     *   meta.requestId          unique per request — a stable React key
     *   meta.fulfilledTimeStamp when the response landed
     *
     * So this reducer is a pure function of its inputs, and replaying the
     * action reproduces the state exactly.
     */
    builder.addMatcher(
      queryApi.endpoints.ask.matchFulfilled,
      (state, action) => {
        state.messages.push({
          id: action.meta.requestId,
          role: "assistant",
          content: action.payload.text,
          sources: action.payload.sources,
          createdAt: action.meta.fulfilledTimeStamp,
        });
      },
    );
  },

  /**
   * Selectors defined on the slice are written against *slice* state and RTK
   * wires them to the right branch of the store automatically — as long as the
   * reducer is mounted under `chatSlice.reducerPath`, which `store/index.ts`
   * guarantees by using that property rather than a string literal.
   *
   * Keeping them here means a component never writes `state.chat.messages`,
   * so reshaping this slice later touches one file instead of every consumer.
   */
  selectors: {
    selectMessages: (state) => state.messages,
    selectHasMessages: (state) => state.messages.length > 0,
  },
});

export const { questionAsked } = chatSlice.actions;
export const { selectMessages, selectHasMessages } = chatSlice.selectors;
