import { useSyncExternalStore } from "react";

/** Минимальный store: состояние, подписка, частичное обновление. */
export interface Store<T> {
  get: () => T;
  set: (patch: Partial<T> | ((s: T) => Partial<T>)) => void;
  subscribe: (fn: () => void) => () => void;
}

export function createStore<T extends object>(init: T): Store<T> {
  let state = init;
  const listeners = new Set<() => void>();
  return {
    get: () => state,
    set(patch) {
      const p = typeof patch === "function" ? patch(state) : patch;
      state = { ...state, ...p };
      listeners.forEach((f) => f());
    },
    subscribe(fn) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
  };
}

/** Подписка компонента на часть состояния. Селектор должен возвращать стабильное значение. */
export function useStore<T, U>(store: Store<T>, sel: (s: T) => U): U {
  return useSyncExternalStore(store.subscribe, () => sel(store.get()));
}
