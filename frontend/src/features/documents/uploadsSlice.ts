/**
 * What this session uploaded.
 *
 * **Not "the documents that exist".** That is server state, it arrives at
 * stage 1.2 with `GET /documents`, and it will live in the RTK Query cache
 * where it belongs. This slice holds a log of *activity in this browser tab*:
 * which uploads were made, in what order, and when.
 *
 * Today the two look identical, because the server list does not exist and the
 * only way to learn a document was indexed is to have indexed it yourself.
 * That coincidence is temporary, and modelling them as one thing would make
 * stage 1.2 a migration instead of an addition.
 *
 * ── What is lost on refresh, and what is not ────────────────────────────────
 *
 * This list clears when the tab reloads. The *index* does not — Qdrant has the
 * chunks on disk and questions still find them. Only the knowledge of what was
 * uploaded is gone, which is precisely the gap stage 1.2 closes and precisely
 * why the sidebar says so on screen.
 *
 * ── Why there is no `uploadRecorded` action ─────────────────────────────────
 *
 * Same reasoning as the transcript: the only way an entry appears is a
 * successful upload. There is no public action a component could dispatch with
 * invented ingest numbers.
 */

import { createSelector, createSlice } from "@reduxjs/toolkit";

import { documentsApi } from "@/services/documentsApi";
import type { IngestedDocument, SessionUpload } from "@/types";

interface UploadsState {
  /** Newest first, so the list reads the way the sidebar renders it. */
  items: SessionUpload[];
}

const initialState: UploadsState = {
  items: [],
};

export const uploadsSlice = createSlice({
  name: "uploads",
  initialState,
  reducers: {},

  extraReducers: (builder) => {
    builder.addMatcher(
      documentsApi.endpoints.uploadDocument.matchFulfilled,
      (state, action) => {
        state.items.unshift({
          // Unique per *attempt*. See the note on `SessionUpload.id`: at stage
          // 2.2, re-uploading the same file returns the same document id, so
          // using that as the key would collide here.
          id: action.meta.requestId,
          document: action.payload,
          uploadedAt: action.meta.fulfilledTimeStamp,
        });
      },
    );
  },

  selectors: {
    selectUploads: (state) => state.items,
    selectHasUploads: (state) => state.items.length > 0,
    selectLatestUpload: (state) => state.items[0] ?? null,
  },
});

export const { selectUploads, selectHasUploads, selectLatestUpload } =
  uploadsSlice.selectors;

/**
 * The uploaded documents, without the session metadata.
 *
 * **Memoised, and it has to be.** `useAppSelector` re-runs its selector after
 * every dispatched action and keeps the result only if it is referentially
 * equal to last time. A plain `(state) => state.uploads.items.map(u =>
 * u.document)` builds a brand-new array on every call, so it is never equal to
 * the previous one, so the component re-renders on *every action in the app* —
 * including every keystroke that touches the store and every RTK Query
 * lifecycle action.
 *
 * `createSelector` caches on the inputs: while `items` is the same reference,
 * the mapped array is the same reference too.
 *
 * The rule worth keeping: **a selector that creates a new object or array must
 * be memoised.** Returning an existing slice of state, or a primitive, does
 * not need it — which is why the three selectors above are plain functions.
 */
export const selectUploadedDocuments = createSelector(
  [selectUploads],
  (uploads): IngestedDocument[] => uploads.map((upload) => upload.document),
);
