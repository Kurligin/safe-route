/* Рисование карты на canvas: площадка, зоны, здания, расхождения карты, прогоны в момент t. */
import type { MapData, Polygon, Pt, ReadyRun } from "../../api/types";
import { palette } from "../../lib/colors";
import { idxAt } from "../../lib/derive";
import { BUILD_RU, DOCK_RU } from "../../lib/labels";
import type { LayerKey } from "../../store/app";

export interface Viewport {
  W: number;
  H: number;
  dpr: number;
  sc: number;
  ox: number;
  oy: number;
}

export type Overlay = (
  ctx: CanvasRenderingContext2D,
  X: (x: number) => number,
  Y: (y: number) => number,
  sc: number,
) => void;

export interface MapScene {
  runs: { key: string; R: ReadyRun; refs: Record<string, Pt[]> }[];
  compareKey: string | null;
  t: number;
  layers: Record<LayerKey, boolean>;
  map: MapData;
  editor: boolean;
  overlay?: Overlay;
}

/** Начальный масштаб и центр: площадка с дорогами целиком. */
export function fitViewport(vp: Viewport): void {
  const bx0 = 8,
    by0 = 66,
    bx1 = 250,
    by1 = 194;
  vp.sc = Math.min((vp.W - 40) / (bx1 - bx0), (vp.H - 40) / (by1 - by0));
  vp.ox = vp.W / 2 - ((bx0 + bx1) / 2) * vp.sc;
  vp.oy = vp.H / 2 + ((by0 + by1) / 2) * vp.sc;
}

export function drawMap(ctx: CanvasRenderingContext2D, vp: Viewport, S: MapScene): void {
  const { W, H, dpr, sc, ox, oy } = vp;
  if (!W) return;
  const C = palette();
  const X = (x: number) => ox + x * sc,
    Y = (y: number) => oy - y * sc;
  const path = (p: Polygon) => {
    ctx.beginPath();
    p.forEach(([x, y], i) => (i ? ctx.lineTo(X(x), Y(y)) : ctx.moveTo(X(x), Y(y))));
    ctx.closePath();
  };
  function poly(p: Polygon, fill: string | null, stroke?: string, lw?: number, dash?: number[]) {
    path(p);
    if (fill) {
      ctx.fillStyle = fill;
      ctx.fill();
    }
    if (stroke) {
      ctx.strokeStyle = stroke;
      ctx.lineWidth = lw || 1;
      ctx.setLineDash(dash || []);
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }
  function hatch(p: Polygon, color: string) {
    ctx.save();
    path(p);
    ctx.clip();
    ctx.strokeStyle = color;
    ctx.lineWidth = 1;
    const xs = p.map((q) => X(q[0])),
      ys = p.map((q) => Y(q[1]));
    const x0 = Math.min(...xs),
      x1 = Math.max(...xs),
      y0 = Math.min(...ys),
      y1 = Math.max(...ys);
    for (let k = x0 - (y1 - y0); k < x1; k += 6) {
      ctx.beginPath();
      ctx.moveTo(k, y1);
      ctx.lineTo(k + (y1 - y0), y0);
      ctx.stroke();
    }
    ctx.restore();
  }
  function robot(x: number, y: number, th: number, color: string, fillA: string | null, dashed?: boolean) {
    const r = Math.max(6, 0.9 * sc);
    ctx.beginPath();
    ctx.arc(X(x), Y(y), r, 0, Math.PI * 2);
    if (fillA) {
      ctx.fillStyle = fillA;
      ctx.fill();
    }
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.setLineDash(dashed ? [4, 3] : []);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.moveTo(X(x), Y(y));
    ctx.lineTo(X(x + Math.cos(th) * 1.5), Y(y + Math.sin(th) * 1.5));
    ctx.stroke();
  }
  function trail(
    R: ReadyRun,
    i: number,
    kx: "x" | "px",
    ky: "y" | "py",
    color: string,
    dash: number[] | null,
    lw: number,
  ) {
    const T = R.ticks;
    ctx.beginPath();
    let started = false;
    for (let k = 0; k <= i; k += 2) {
      const x = T[kx][k],
        y = T[ky][k];
      if (x == null || y == null) {
        started = false;
        continue;
      }
      if (!started) {
        ctx.moveTo(X(x), Y(y));
        started = true;
      } else ctx.lineTo(X(x), Y(y));
    }
    ctx.strokeStyle = color;
    ctx.lineWidth = lw;
    ctx.setLineDash(dash || []);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  const R = S.runs.length ? S.runs[0].R : null;
  const M = S.map,
    L = S.layers;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.fillStyle = C.view;
  ctx.fillRect(0, 0, W, H);
  // сетка 10 м
  ctx.strokeStyle = "rgba(255,255,255,0.035)";
  ctx.lineWidth = 1;
  for (let x = 0; x <= 250; x += 10) {
    ctx.beginPath();
    ctx.moveTo(X(x), Y(0));
    ctx.lineTo(X(x), Y(200));
    ctx.stroke();
  }
  for (let y = 0; y <= 200; y += 10) {
    ctx.beginPath();
    ctx.moveTo(X(0), Y(y));
    ctx.lineTo(X(250), Y(y));
    ctx.stroke();
  }
  M.drivable.forEach((p) => poly(p, "#23272f"));
  if (L.zones || S.editor) {
    M.zones.forEach((z) => {
      if (z.type === "gnss_shadow") poly(z.polygon, "rgba(155,107,214,0.16)", "rgba(155,107,214,0.55)", 1, [5, 4]);
      if (z.type === "people_area") poly(z.polygon, "rgba(90,168,111,0.07)", "rgba(90,168,111,0.35)", 1, [2, 4]);
      if (z.type === "speed_limit") poly(z.polygon, "rgba(201,162,39,0.07)", "rgba(201,162,39,0.5)", 1, [6, 3]);
      if (z.type === "forbidden") {
        poly(z.polygon, "rgba(196,89,90,0.12)", "rgba(196,89,90,0.7)", 1);
        hatch(z.polygon, "rgba(196,89,90,0.45)");
      }
    });
  }
  M.buildings.forEach((b) => poly(b.polygon, "#3a3f4a", "#4a505c", 1));
  if (R && L.patches)
    R.patches.forEach((p) => {
      if (p.op === "add" && p.polygon) {
        poly(p.polygon, "rgba(196,89,90,0.25)", C.bad, 1.5);
        hatch(p.polygon, "rgba(196,89,90,0.6)");
      } else {
        const b = M.buildings.find((q) => q.id === p.id);
        if (b) poly(b.polygon, null, C.bad, 1.5, [3, 3]);
      }
    });
  // подписи зданий
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  M.buildings.forEach((b) => {
    const ru = BUILD_RU[b.id];
    if (!ru) return;
    const xs = b.polygon.map((q) => q[0]),
      ys = b.polygon.map((q) => q[1]);
    const cx = X((Math.max(...xs) + Math.min(...xs)) / 2),
      cy = Y((Math.max(...ys) + Math.min(...ys)) / 2);
    const w = (Math.max(...xs) - Math.min(...xs)) * sc;
    const fs = Math.max(9, Math.min(13, w / 9));
    ctx.font = `600 ${fs}px Inter, sans-serif`;
    ctx.fillStyle = "rgba(232,234,237,0.55)";
    if (w > ctx.measureText(ru).width + 6) ctx.fillText(ru, cx, cy);
    else {
      ctx.save();
      ctx.translate(cx, cy);
      ctx.rotate(-Math.PI / 2);
      ctx.fillText(ru, 0, 0);
      ctx.restore();
    }
  });
  ctx.font = "500 10px Inter, sans-serif";
  ctx.fillStyle = "rgba(232,234,237,0.45)";
  ctx.textAlign = "left";
  if (sc >= 5) {
    ctx.fillText("Киоск", X(72.8), Y(122));
    ctx.fillText("Навес", X(205), Y(102.2));
    ctx.save();
    ctx.translate(X(54), Y(118));
    ctx.rotate(-Math.PI / 2);
    ctx.textAlign = "center";
    ctx.fillText("Забор", 0, 0);
    ctx.restore();
  }
  // точки
  const points = (R && R.points) || M.points || {};
  Object.entries(points).forEach(([name, p]) => {
    ctx.beginPath();
    ctx.arc(X(p.x), Y(p.y), 4, 0, Math.PI * 2);
    ctx.fillStyle = C.fg;
    ctx.fill();
    if (sc < 5) return;
    ctx.font = "500 11px Inter, sans-serif";
    ctx.fillStyle = C.fg2;
    ctx.textAlign = "center";
    ctx.fillText(DOCK_RU[name] || name, X(p.x) - (name === "shop_b" ? 22 : 0), Y(p.y) + 14);
    ctx.textAlign = "left";
  });
  S.runs.forEach(({ key, R: Rk, refs }, ki) => {
    const i = idxAt(Rk, S.t),
      T = Rk.ticks;
    const cm = !!S.compareKey && key === S.compareKey;
    const col = cm ? C.cmp : C.accent;
    // путь текущего рейса
    if (L.path && ki === 0) {
      const mid = T.m[i];
      const ref = mid ? refs[mid] : null;
      if (ref && ref.length) {
        ctx.beginPath();
        ref.forEach(([x, y], k) => (k ? ctx.lineTo(X(x), Y(y)) : ctx.moveTo(X(x), Y(y))));
        ctx.strokeStyle = "rgba(232,234,237,0.18)";
        ctx.lineWidth = 3;
        ctx.stroke();
      }
    }
    if (L.trail) trail(Rk, i, "x", "y", cm ? "rgba(232,119,46,0.75)" : "rgba(74,140,255,0.75)", null, 1.6);
    if (L.est) trail(Rk, i, "px", "py", cm ? "rgba(232,119,46,0.9)" : "rgba(232,234,237,0.55)", [4, 4], 1.2);
    // упавший предмет
    Rk.events
      .filter((e) => e.type === "object_dropped" && S.t >= (e.t ?? 0))
      .forEach((e) => {
        ctx.beginPath();
        ctx.arc(X(e.x ?? 0), Y(e.y ?? 0), Math.max(3, (e.r ?? 0.4) * sc), 0, Math.PI * 2);
        ctx.fillStyle = "#8a6b3f";
        ctx.fill();
        ctx.strokeStyle = C.warn;
        ctx.lineWidth = 1.5;
        ctx.stroke();
      });
    if (L.peds && ki === 0) {
      (T.peds[i] || []).forEach(([px, py]) => {
        const gap = Math.hypot(px - T.x[i], py - T.y[i]) - 1.2;
        ctx.beginPath();
        ctx.arc(X(px), Y(py), Math.max(3.5, 0.3 * sc), 0, Math.PI * 2);
        ctx.fillStyle = gap < 3 ? C.bad : "#e8eaed";
        ctx.fill();
        if (gap < 3) {
          ctx.beginPath();
          ctx.arc(X(px), Y(py), 3.3 * sc, 0, Math.PI * 2);
          ctx.strokeStyle = "rgba(196,89,90,0.35)";
          ctx.lineWidth = 1;
          ctx.stroke();
        }
      });
    }
    const px = T.px[i],
      py = T.py[i],
      pth = T.pth[i];
    if (L.est && px != null && py != null) robot(px, py, pth ?? 0, cm ? C.cmp : "rgba(232,234,237,0.8)", null, true);
    robot(T.x[i], T.y[i], T.th[i], col, cm ? "rgba(232,119,46,0.25)" : "rgba(74,140,255,0.28)");
  });
  if (S.overlay) S.overlay(ctx, X, Y, sc);
  // масштабная линейка
  const m10 = 10 * sc;
  ctx.strokeStyle = C.fg2;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(W - 56 - m10, H - 20);
  ctx.lineTo(W - 56, H - 20);
  ctx.stroke();
  ctx.fillStyle = C.fg2;
  ctx.font = "11px JetBrains Mono, monospace";
  ctx.textAlign = "right";
  ctx.fillText("10 м", W - 56, H - 28);
}
