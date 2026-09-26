/* Нижняя шкала: ось времени, условия, рейсы, остановки и графики скорости, ошибки позы и зазора. */
import type { ReadyRun } from "../../api/types";
import { palette } from "../../lib/colors";
import type { Derived } from "../../lib/derive";
import { fmtT } from "../../lib/format";

export const LX = 118;
export const RX = 14;

interface Row {
  k: "axis" | "cond" | "miss" | "stop" | "v" | "err" | "hum";
  h: number;
  lbl?: string;
  max?: number;
}
const ROWS: Row[] = [
  { k: "axis", h: 16 },
  { k: "cond", h: 12, lbl: "условия" },
  { k: "miss", h: 12, lbl: "рейсы" },
  { k: "stop", h: 12, lbl: "остановки" },
  { k: "v", h: 34, lbl: "скорость, м/с", max: 1.5 },
  { k: "err", h: 34, lbl: "ошибка позы, м", max: 2 },
  { k: "hum", h: 34, lbl: "зазор до чел., м", max: 8 },
];

export function drawTracks(
  ctx: CanvasRenderingContext2D,
  W: number,
  H: number,
  dpr: number,
  runs: { R: ReadyRun; d: Derived }[],
  t: number,
  tMax: number,
): void {
  if (!W) return;
  const C = palette();
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);
  if (!runs.length) return;
  const TX = (tt: number) => LX + (tt / tMax) * (W - LX - RX);
  const total = ROWS.reduce((a, r) => a + r.h + 4, 0);
  const k = (H - 6) / total;
  let y = 4;
  ctx.font = "11px Inter, sans-serif";
  ctx.textBaseline = "middle";
  const two = runs.length > 1;
  ROWS.forEach((row) => {
    const h = row.h * k;
    if (row.lbl) {
      ctx.fillStyle = C.fg2;
      ctx.textAlign = "right";
      ctx.fillText(row.lbl, LX - 10, y + h / 2);
    }
    if (row.k === "axis") {
      const step = tMax > 300 ? 60 : 30;
      ctx.fillStyle = C.fg3;
      ctx.textAlign = "center";
      ctx.font = "10px JetBrains Mono, monospace";
      for (let tt = 0; tt <= tMax; tt += step) {
        ctx.fillText(fmtT(tt).replace(".0", ""), TX(tt), y + h / 2);
        ctx.fillStyle = "rgba(255,255,255,0.04)";
        ctx.fillRect(TX(tt), y + h, 1, H);
        ctx.fillStyle = C.fg3;
      }
      ctx.font = "11px Inter, sans-serif";
    } else if (row.k === "cond") {
      ctx.fillStyle = "rgba(255,255,255,0.03)";
      ctx.fillRect(LX, y, W - LX - RX, h);
      const d = runs[0].d;
      d.shadow.forEach(([a, b]) => {
        ctx.fillStyle = "rgba(155,107,214,0.65)";
        ctx.fillRect(TX(a), y, TX(b) - TX(a), h);
      });
      d.fog.forEach(([a, b]) => {
        ctx.fillStyle = "rgba(154,160,170,0.55)";
        ctx.fillRect(TX(a), y + h / 2, TX(b) - TX(a), h / 2);
      });
      d.outage.forEach(([a, b]) => {
        ctx.fillStyle = "rgba(196,89,90,0.7)";
        ctx.fillRect(TX(a), y, TX(b) - TX(a), h / 3);
      });
      d.drops.forEach((e) => {
        const et = e.t ?? 0;
        ctx.fillStyle = C.warn;
        ctx.beginPath();
        ctx.moveTo(TX(et), y);
        ctx.lineTo(TX(et) + 5, y + h);
        ctx.lineTo(TX(et) - 5, y + h);
        ctx.fill();
      });
    } else if (row.k === "miss") {
      runs.forEach(({ d }, ki) => {
        d.mBands.forEach((m) => {
          ctx.fillStyle = m.ok ? (ki ? "rgba(232,119,46,0.55)" : "rgba(90,168,111,0.6)") : "rgba(196,89,90,0.7)";
          const yy = two ? y + (ki * h) / 2 : y,
            hh = two ? h / 2 - 1 : h;
          ctx.fillRect(TX(m.t0) + 1, yy, TX(m.t1) - TX(m.t0) - 2, hh);
          if (!two) {
            ctx.fillStyle = "#0b0d11";
            ctx.textAlign = "left";
            ctx.font = "600 10px Inter";
            ctx.fillText(m.id + (m.ok ? " ✓" : " ✗"), TX(m.t0) + 4, y + h / 2 + 1);
            ctx.font = "11px Inter, sans-serif";
          }
        });
      });
    } else if (row.k === "stop") {
      runs.forEach(({ d }, ki) => {
        const yy = two ? y + (ki * h) / 2 : y,
          hh = two ? h / 2 - 1 : h;
        d.stops.forEach((s) => {
          ctx.fillStyle = s.full ? (ki ? C.cmp : C.warn) : ki ? "rgba(232,119,46,0.45)" : "rgba(201,162,39,0.45)";
          ctx.fillRect(TX(s.t0), yy, Math.max(2, TX(s.t1) - TX(s.t0)), hh);
        });
        d.episodes.forEach((e) => {
          ctx.fillStyle = C.bad;
          ctx.beginPath();
          ctx.arc(TX(e.t_start), yy + hh / 2, 3.5, 0, Math.PI * 2);
          ctx.fill();
        });
      });
    } else {
      const max = row.max || 1;
      ctx.fillStyle = "rgba(255,255,255,0.025)";
      ctx.fillRect(LX, y, W - LX - RX, h);
      const Yv = (v: number) => y + h - (Math.min(max, Math.max(0, v)) / max) * h;
      const hline = (v: number, color: string) => {
        ctx.strokeStyle = color;
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(LX, Yv(v));
        ctx.lineTo(W - RX, Yv(v));
        ctx.stroke();
        ctx.setLineDash([]);
      };
      if (row.k === "err") hline(1, "rgba(196,89,90,0.6)");
      if (row.k === "hum") {
        hline(3, "rgba(201,162,39,0.55)");
        hline(0.5, "rgba(196,89,90,0.6)");
      }
      runs.forEach(({ R }, ki) => {
        const T = R.ticks;
        const n = T.t.length;
        const stepk = Math.max(1, Math.floor(n / (W - LX)));
        if (row.k === "v" && ki === 0) {
          ctx.strokeStyle = "rgba(201,162,39,0.5)";
          ctx.lineWidth = 1;
          ctx.beginPath();
          for (let i = 0; i < n; i += stepk) {
            const vm = T.vmax[i] == null ? 1.39 : (T.vmax[i] as number);
            const xx = TX(T.t[i]);
            if (i) ctx.lineTo(xx, Yv(vm));
            else ctx.moveTo(xx, Yv(vm));
          }
          ctx.stroke();
        }
        ctx.strokeStyle = ki ? C.cmp : C.accent;
        ctx.lineWidth = 1.3;
        ctx.beginPath();
        let st = false;
        for (let i = 0; i < n; i += stepk) {
          const v = row.k === "v" ? Math.abs(T.v[i]) : row.k === "err" ? T.err[i] : T.hum[i];
          if (v == null) {
            st = false;
            continue;
          }
          const xx = TX(T.t[i]),
            yy = Yv(v);
          if (!st) {
            ctx.moveTo(xx, yy);
            st = true;
          } else ctx.lineTo(xx, yy);
        }
        ctx.stroke();
      });
      ctx.fillStyle = C.fg3;
      ctx.textAlign = "left";
      ctx.font = "10px JetBrains Mono, monospace";
      ctx.fillText(String(max), LX + 3, y + 7);
      ctx.font = "11px Inter, sans-serif";
    }
    y += h + 4 * k;
  });
  // курсор
  const cx = TX(t);
  ctx.strokeStyle = C.fg;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(cx, 4);
  ctx.lineTo(cx, H);
  ctx.stroke();
  ctx.fillStyle = C.fg;
  ctx.beginPath();
  ctx.moveTo(cx - 5, 2);
  ctx.lineTo(cx + 5, 2);
  ctx.lineTo(cx, 8);
  ctx.fill();
}
