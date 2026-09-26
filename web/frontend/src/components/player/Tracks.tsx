import { useEffect, useRef } from "react";
import { app, clock, derived, readyRun, seek, tMax } from "../../store/app";
import { drawTracks, LX, RX } from "./drawTracks";

/** Шкала и графики под картой; клик и перетаскивание — перемотка. */
export function Tracks() {
  const hostRef = useRef<HTMLDivElement>(null);
  const cvRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const host = hostRef.current!,
      cv = cvRef.current!;
    const ctx = cv.getContext("2d")!;
    let W = 0,
      H = 0,
      dpr = 1,
      frame = 0;
    const draw = () => {
      const s = app.get();
      const keys = (s.compare ? [s.primary, s.compare] : [s.primary]).filter(Boolean);
      const runs = keys
        .map((k) => readyRun(k))
        .filter((R): R is NonNullable<typeof R> => !!R)
        .map((R) => ({ R, d: derived(R) }));
      drawTracks(ctx, W, H, dpr, runs, clock.get().t, tMax());
    };
    const fit = () => {
      const r = host.getBoundingClientRect();
      W = r.width;
      H = r.height;
      dpr = window.devicePixelRatio || 1;
      cv.width = W * dpr;
      cv.height = H * dpr;
      draw();
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(() => ((frame = 0), draw()));
    };
    let down = false;
    const toT = (e: MouseEvent) => {
      const r = cv.getBoundingClientRect();
      return ((e.clientX - r.left - LX) / (W - LX - RX)) * tMax();
    };
    const onDown = (e: MouseEvent) => {
      down = true;
      seek(toT(e), false);
    };
    const onMove = (e: MouseEvent) => {
      if (down) seek(toT(e), false);
    };
    const onUp = () => (down = false);
    cv.addEventListener("mousedown", onDown);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    const ro = new ResizeObserver(fit);
    ro.observe(host);
    const unA = app.subscribe(schedule),
      unC = clock.subscribe(schedule);
    document.fonts?.ready.then(schedule);
    return () => {
      cv.removeEventListener("mousedown", onDown);
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      ro.disconnect();
      unA();
      unC();
      cancelAnimationFrame(frame);
    };
  }, []);

  return (
    <div className="tracks" id="tracks" ref={hostRef}>
      <canvas ref={cvRef} />
    </div>
  );
}
