/**
 * Typed Redux hooks.
 *
 * Every component imports `useAppDispatch` and `useAppSelector` from here
 * rather than `useDispatch` and `useSelector` from react-redux. The untyped
 * versions know nothing about this store, so `useSelector((s) => s.chat)`
 * would be `any` — and `s.chta` would compile.
 *
 * Pre-typing them once is the standard Redux Toolkit pattern and it is the
 * difference between selectors being checked and selectors being hope.
 *
 * `useAppDispatch` matters for a second reason: `AppDispatch` carries the
 * thunk middleware's types, so dispatching a thunk returns a promise you can
 * `.unwrap()`. The plain `useDispatch` types that as an error.
 */

import { useDispatch, useSelector } from "react-redux";

import type { AppDispatch, RootState } from "./index";

export const useAppDispatch = useDispatch.withTypes<AppDispatch>();
export const useAppSelector = useSelector.withTypes<RootState>();
