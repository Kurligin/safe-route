import { useCallback, useEffect, useRef, type ReactNode } from "react";
import type { MapData } from "../../api/types";
import { idxAt } from "../../lib/derive";
import { app, clock, derived, readyRun } from "../../store/app";
import { drawMap, fitViewport, type Overlay, type Viewport } from "./drawMap";

interface Props {
  /** Прогоны на карте: первый — основной, второй — сравнение. */
  keys: (string | null)[];
  editor?: boolean;
  getMap?: () => MapData;
  overlay?: Overlay;
  onClick?: (x: number, y: number) => void;
  /** Любое значение, при смене которого карта перерисовывается (правки конструктора). */
  redrawKey?: unknown;
  id?: string;
  children?: ReactNode;
}

/** Карта площадки на canvas: перетаскивание, колесо, кнопки масштаба, слежение за тележкой. */
export function MapView({ keys, editor, getMap, overlay, onClick, redrawKey, id, children }: Props) {
  const hostRef = useRef<HTMLElement>(null);
  const cvRef = useRef<HTMLCanvasElement>(null);
  const vp = useRef<Viewport>({ W: 0, H: 0, dpr: 1, sc: 4, ox: 0, oy: 0 });
  const fitted = useRef(false);
  const props = useRef({ keys, editor, getMap, overlay, onClick });
  props.current = { keys, editor, getMap, overlay, onClick };

  const readyKeys = () => (props.current.editor ? [] : props.current.keys.filter((k): k is string => !!readyRun(k)));

  const paint = useCallback(() => {
    const cv = cvRef.current;
    const ctx = cv && cv.getContext("2d");
    if (!ctx) return;
    const s = app.get();
    const runs = readyKeys().map((key) => {
      const R = readyRun(key)!;
      return { key, R, refs: derived(R).refs };
    });
    const P = props.current;
    const map = P.getMap ? P.getMap() : (runs[0] && runs[0].R.map) || s.baseMap;
    drawMap(ctx, vp.current, {
      runs,
      compareKey: s.compare,
      t: clock.get().t,
      layers: s.layers,
      map,
      editor: !!P.editor,
      overlay: P.overlay,
    });
  }, []);

  /** Перерисовка по данным: при слежении карта держит тележку в центре. */
  const redraw = useCallback(() => {
    const k = readyKeys()[0];
    if (app.get().follow && k) {
      const R = readyRun(k)!,
        i = idxAt(R, clock.get().t);
      const v = vp.current;
      v.ox = v.W / 2 - R.ticks.x[i] * v.sc;
      v.oy = v.H / 2 + R.ticks.y[i] * v.sc;
    }
    paint();
  }, [paint]);

  const fit = useCallback(() => {
    const host = hostRef.current,
      cv = cvRef.current;
    if (!host || !cv) return;
    const r = host.getBoundingClientRect();
    const v = vp.current;
    v.W = r.width;
    v.H = r.height;
    v.dpr = window.devicePixelRatio || 1;
    cv.width = v.W * v.dpr;
    cv.height = v.H * v.dpr;
    if (!fitted.current && v.W > 0) {
      fitViewport(v);
      fitted.current = true;
    }
    redraw();
  }, [redraw]);

  useEffect(() => {
    let frame = 0;
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(() => ((frame = 0), redraw()));
    };
    const unA = app.subscribe(schedule);
    const unC = clock.subscribe(schedule);
    const ro = new ResizeObserver(fit);
    if (hostRef.current) ro.observe(hostRef.current);
    document.fonts?.ready.then(schedule);
    return () => {
      unA();
      unC();
      ro.disconnect();
      cancelAnimationFrame(frame);
    };
  }, [fit, redraw]);

  useEffect(() => {
    redraw();
  }, [redraw, redrawKey, keys.join("|")]);

  // перетаскивание, клик, колесо
  useEffect(() => {
    const cv = cvRef.current!;
    let drag: [number, number, number, number] | null = null;
    const down = (e: MouseEvent) => {
      const v = vp.current;
      drag = [e.clientX, e.clientY, v.ox, v.oy];
      if (app.get().follow) app.set({ follow: false });
    };
    const up = (e: MouseEvent) => {
      const click = props.current.onClick;
      if (drag && click && Math.hypot(e.clientX - drag[0], e.clientY - drag[1]) < 4) {
        const r = cv.getBoundingClientRect(),
          v = vp.current;
        click((e.clientX - r.left - v.ox) / v.sc, (v.oy - (e.clientY - r.top)) / v.sc);
      }
      drag = null;
    };
    const move = (e: MouseEvent) => {
      if (!drag) return;
      const v = vp.current;
      v.ox = drag[2] + e.clientX - drag[0];
      v.oy = drag[3] + e.clientY - drag[1];
      paint();
    };
    const wheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = cv.getBoundingClientRect(),
        v = vp.current;
      const mx = e.clientX - r.left,
        my = e.clientY - r.top;
      const k = Math.exp(-e.deltaY * 0.0015);
      const wx = (mx - v.ox) / v.sc,
        wy = (v.oy - my) / v.sc;
      v.sc *= k;
      v.ox = mx - wx * v.sc;
      v.oy = my + wy * v.sc;
      paint();
    };
    cv.addEventListener("mousedown", down);
    cv.addEventListener("wheel", wheel, { passive: false });
    window.addEventListener("mouseup", up);
    window.addEventListener("mousemove", move);
    return () => {
      cv.removeEventListener("mousedown", down);
      cv.removeEventListener("wheel", wheel);
      window.removeEventListener("mouseup", up);
      window.removeEventListener("mousemove", move);
    };
  }, [paint]);

  const zoom = (k: number) => {
    const v = vp.current;
    const cx = v.W / 2,
      cy = v.H / 2,
      wx = (cx - v.ox) / v.sc,
      wy = (v.oy - cy) / v.sc;
    v.sc *= k;
    v.ox = cx - wx * v.sc;
    v.oy = cy + wy * v.sc;
    paint();
  };
  const toFit = () => {
    if (app.get().follow) app.set({ follow: false });
    fitted.current = false;
    fit();
  };
  const toBot = () => {
    const k = readyKeys()[0];
    if (!k) return;
    const R = readyRun(k)!,
      i = idxAt(R, clock.get().t),
      v = vp.current;
    v.sc = Math.max(v.sc, 9);
    v.ox = v.W / 2 - R.ticks.x[i] * v.sc;
    v.oy = v.H / 2 + R.ticks.y[i] * v.sc;
    paint();
  };

  return (
    <section className="view" id={id} ref={hostRef}>
      <canvas ref={cvRef} />
      <div className="mapctl">
        <button title="Приблизить" onClick={() => zoom(1.35)}>
          +
        </button>
        <button title="Отдалить" onClick={() => zoom(1 / 1.35)}>
          −
        </button>
        <span className="sep" />
        <button title="Вся площадка" onClick={toFit}>
          <svg viewBox="0 0 16 16">
            <path d="M2 6V2h4M10 2h4v4M14 10v4h-4M6 14H2v-4" fill="none" stroke="currentColor" strokeWidth="1.6" />
          </svg>
        </button>
        {!editor && (
          <button title="К тележке" onClick={toBot}>
            <svg viewBox="0 0 16 16">
              <circle cx="8" cy="8" r="3" fill="none" stroke="currentColor" strokeWidth="1.6" />
              <path d="M8 1v3M8 12v3M1 8h3M12 8h3" stroke="currentColor" strokeWidth="1.6" />
            </svg>
          </button>
        )}
      </div>
      {children}
    </section>
  );
}
