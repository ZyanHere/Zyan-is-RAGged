/**
 * Application chrome.
 *
 * The weakest of the three slices, and worth saying so rather than pretending
 * otherwise: `sidebarOpen` has two consumers today and could perfectly well be
 * a `useState` in `page.tsx`.
 *
 * Two reasons it is here anyway:
 *
 * **It is chrome, not content.** The sidebar belongs to the application shell
 * rather than to any one screen. At stage 5.2 a header with a user menu will
 * also want to close it, and at that point the toggle has consumers in
 * unrelated subtrees — the exact condition that makes lifting insufficient.
 *
 * **It keeps the taxonomy honest.** Having a `ui` slice makes "which of the
 * three kinds is this?" a question with a real answer for every new piece of
 * state. Without one, UI state quietly accumulates in whichever component
 * happened to need it first.
 *
 * What does *not* belong here, and this is the line that matters: anything
 * that changes at interaction rate. The composer's text, a scroll position, a
 * hover state. Those dispatch per keystroke or per frame, flood DevTools, and
 * re-render every subscriber. They stay local. The test is
 * **"does anything outside this component read it?"** — and for a textarea's
 * value, nothing ever does.
 */

import { createSlice } from "@reduxjs/toolkit";

interface UiState {
  /**
   * Only meaningful below the `lg` breakpoint, where the sidebar is an
   * overlay. Above it the sidebar is always visible and this is ignored —
   * which is why the state is a plain boolean and not a tri-state: the
   * breakpoint is a CSS concern and stays in CSS.
   */
  sidebarOpen: boolean;
}

const initialState: UiState = {
  sidebarOpen: false,
};

export const uiSlice = createSlice({
  name: "ui",
  initialState,

  reducers: {
    sidebarOpened(state) {
      state.sidebarOpen = true;
    },
    sidebarClosed(state) {
      state.sidebarOpen = false;
    },
  },

  selectors: {
    selectSidebarOpen: (state) => state.sidebarOpen,
  },
});

export const { sidebarOpened, sidebarClosed } = uiSlice.actions;
export const { selectSidebarOpen } = uiSlice.selectors;
