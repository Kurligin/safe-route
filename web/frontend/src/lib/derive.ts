/* Производные данные прогона для шкалы и таблиц; порядок и пары прогонов. */
import type {
  Episode,
  MapData,
  MissionRecord,
  Polygon,
  Pt,
  ReadyRun,
  Run,
  Scenario,
  ScenItem,
  SimEvent,
  Stop,
  Ticks,
} from "../api/types";
import { GROUPS } from "./labels";

export function inside(x: number, y: number, poly: Polygon): boolean {
  let c = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [x1, y1] = poly[i],
      [x2, y2] = poly[j];
    if (y1 > y !== y2 > y && x < x1 + ((y - y1) * (x2 - x1)) / (y2 - y1)) c = !c;
  }
  return c;
}

function bandsWhere(T: Ticks, pred: (i: number) => boolean): [number, number][] {
  const out: [number, number][] = [];
  let s: number | null = null;
  for (let i = 0; i < T.t.length; i++) {
    const on = pred(i);
    if (on && s == null) s = T.t[i];
    if (!on && s != null) {
      out.push([s, T.t[i]]);
      s = null;
    }
  }
  if (s != null) out.push([s, T.t[T.t.length - 1]]);
  return out;
}

export interface Derived {
  tEnd: number;
  shadow: [number, number][];
  fog: [number, number][];
  outage: [number, number][];
  drops: SimEvent[];
  stops: Stop[];
  episodes: Episode[];
  trips: MissionRecord[];
  mBands: { id: string; t0: number; t1: number; ok: boolean }[];
  refs: Record<string, Pt[]>;
}

const cache = new WeakMap<Run, Derived>();

export const isReady = (R: Run | undefined | null): R is ReadyRun => !!(R && R.ticks && R.stops);

/** Производные прогона (кэш на объект прогона: перезапуск даёт новый объект). */
export function derive(R: ReadyRun, baseMap: MapData | null, scens: Record<string, Scenario>): Derived {
  const hit = cache.get(R);
  if (hit) return hit;
  const T = R.ticks,
    n = T.t.length;
  const shadows = ((R.map || baseMap)?.zones || []).filter((z) => z.type === "gnss_shadow").map((z) => z.polygon);
  // эталонные пути рейсов: из сценария, иначе — по следу тележки
  const refs: Record<string, Pt[]> = {};
  const sc = scens[R.scenario];
  if (sc) sc.missions.forEach((m) => (refs[m.id] = m.ref));
  for (let i = 0; i < n; i += 5) {
    const m = T.m[i];
    if (!m || (sc && refs[m])) continue;
    (refs[m] = refs[m] || []).push([T.x[i], T.y[i]]);
  }
  const d: Derived = {
    tEnd: n ? T.t[n - 1] : 0,
    shadow: bandsWhere(T, (i) => shadows.some((p) => inside(T.x[i], T.y[i], p))),
    fog: R.events.filter((e) => e.type === "fog_bank").map((e) => [e.t1 ?? 0, e.t2 ?? 0]),
    outage: R.events.filter((e) => e.type === "gnss_outage").map((e) => [e.t1 ?? 0, e.t2 ?? 0]),
    drops: R.events.filter((e) => e.type === "object_dropped"),
    stops: R.stops,
    episodes: R.score.episodes || [],
    trips: R.missions,
    mBands: R.missions.map((m) => ({ id: m.id, t0: m.t_start, t1: m.t_end, ok: m.delivered })),
    refs,
  };
  cache.set(R, d);
  return d;
}

/** Индекс тика для момента t (двоичный поиск). */
export function idxAt(R: ReadyRun, t: number): number {
  const a = R.ticks.t;
  let lo = 0,
    hi = a.length - 1;
  if (hi < 0 || t <= a[0]) return 0;
  if (t >= a[hi]) return hi;
  while (hi - lo > 1) {
    const m = (lo + hi) >> 1;
    if (a[m] <= t) lo = m;
    else hi = m;
  }
  return lo;
}

const CTRL_ORDER: Record<string, number> = { ours: 0, baseline: 1 };

/** Порядок прогонов в списке: группа сценария, сценарий, контроллер, seed. */
export function runOrder(runs: Record<string, Run>, list: ScenItem[]): string[] {
  const gIdx = (id: string) => {
    const s = list.find((q) => q.id === id);
    return s ? GROUPS.indexOf(s.group) : 99;
  };
  return Object.keys(runs).sort((a, b) => {
    const A = runs[a],
      B = runs[b];
    return (
      gIdx(A.scenario) - gIdx(B.scenario) ||
      A.scenario.localeCompare(B.scenario) ||
      (CTRL_ORDER[A.ctrl] ?? 9) - (CTRL_ORDER[B.ctrl] ?? 9) ||
      A.seed - B.seed ||
      a.localeCompare(b)
    );
  });
}

export const sameScen = (k: string, order: string[], runs: Record<string, Run>): string[] =>
  order.filter((x) => x !== k && runs[x].scenario === runs[k].scenario);

/** Пара для сравнения: другой контроллер на том же seed, затем другой контроллер, затем другой seed. */
export function pairFor(k: string | null, order: string[], runs: Record<string, Run>): string | null {
  if (!k || !runs[k]) return null;
  const R = runs[k],
    c = sameScen(k, order, runs);
  const rank = (x: string) => (runs[x].ctrl !== R.ctrl ? 0 : 2) + (runs[x].seed === R.seed ? 0 : 1);
  c.sort((a, b) => rank(a) - rank(b));
  return c[0] || null;
}
