import { useEffect, useState } from "react";
import { app, clock } from "./app";

/** Время для панелей: во время проигрывания обновляется не чаще раза в `ms` мс. */
export function useThrottledT(ms: number): number {
  const [t, setT] = useState(clock.get().t);
  useEffect(() => {
    let last = 0;
    const on = () => {
      const now = performance.now();
      if (app.get().playing && now - last < ms) return;
      last = now;
      setT(clock.get().t);
    };
    const u1 = clock.subscribe(on),
      u2 = app.subscribe(on);
    return () => {
      u1();
      u2();
    };
  }, [ms]);
  return t;
}

/** Время для подсветки строк таблиц: меняется, когда сменился двухсекундный отрезок и нет проигрывания. */
export function useStableT(): number {
  const [t, setT] = useState(clock.get().t);
  useEffect(() => {
    let bucket = Math.floor(clock.get().t / 2);
    const on = () => {
      const tt = clock.get().t,
        k = Math.floor(tt / 2);
      if (!app.get().playing && k !== bucket) {
        bucket = k;
        setT(tt);
      }
    };
    const u1 = clock.subscribe(on),
      u2 = app.subscribe(on);
    return () => {
      u1();
      u2();
    };
  }, []);
  return t;
}
