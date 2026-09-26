/* Модель конструктора сценария: состояние, разбор существующего сценария, сборка amr-1.0, проверки.
   Карта и маршруты берутся из реальных сценариев; у открытого сценария — его собственная карта. */
import { api } from "../../api/client";
import type { MapData, Polygon, Pt, Scenario, ScenMission, SimEvent } from "../../api/types";
import { inside } from "../../lib/derive";
import { ptRu, scenRu } from "../../lib/labels";
import { app } from "../../store/app";
import { createStore } from "../../store/createStore";

export type Tool = "ped" | "ped_in" | "pallet" | "box" | "remove";

export interface Ped {
  inatt: boolean;
  pts: Pt[];
  speed: number;
  t0: number;
  loop: boolean;
}
export interface Pallet {
  x: number;
  y: number;
  t: number;
  r: number;
}
export interface Box {
  x?: number;
  y?: number;
  poly?: Polygon;
  id?: string;
}

export interface BState {
  tool: Tool;
  peds: Ped[];
  cur: Ped | null;
  pallets: Pallet[];
  boxes: Box[];
  removed: string[];
  route: string;
  missions: ScenMission[] | null;
  duration: number | null;
  snow: boolean;
  fog: [number, number];
  fogOn: boolean;
  gnss: [number, number];
  gnssOn: boolean;
  name: string;
  src: string; // "new" или "sc:<id>"
  id: string | null;
  ro: boolean;
  msg: ["ok" | "bad", string] | null;
  busy: boolean;
  map: MapData | null;
  det: boolean;
  generator: unknown;
  extraEv: SimEvent[];
}

export const TOOLS: [Tool, string, string][] = [
  [
    "ped",
    "Пешеход",
    "Кликайте по карте — каждая точка станет точкой пути. Внимательный пешеход останавливается перед движущейся тележкой.",
  ],
  [
    "ped_in",
    "Невнимательный пешеход",
    "Как пешеход, но не уступает дорогу движущейся тележке. Проверяет прогноз и остановку.",
  ],
  ["pallet", "Поддон", "Появится на дороге в заданный момент. Тележка должна заметить и объехать или остановиться."],
  [
    "box",
    "Контейнер (нет на карте)",
    "Препятствие 6×2,5 м, которого нет на карте. Проверяет расхождение карты с миром.",
  ],
  [
    "remove",
    "Снести здание",
    "Клик по зданию: на карте оно останется, в мире исчезнет. Проверяет устойчивость локализации к изменённой карте.",
  ],
];

/* ---------------------------------------------------------------- маршруты */
export interface Route {
  ru: string;
  src: string;
  missions: ScenMission[];
  duration: number | null;
}
const routeKey = (ms: ScenMission[]) => (ms.length ? [ms[0].from].concat(ms.map((m) => m.to)).join(">") : "");

let routesFor: Record<string, Scenario> | null = null;
let routesCache: Record<string, Route> = {};
/** Маршруты «склад → цех A → склад» и т. п. из реальных сценариев (первым — из открытых). */
export function routes(): Record<string, Route> {
  const scens = app.get().scens;
  if (routesFor === scens) return routesCache;
  const pref = ["04_busy_yard", "02_gnss_shadow", "03_fog_snow", "01_clear"];
  const ids = pref
    .filter((id) => scens[id])
    .concat(
      Object.keys(scens)
        .sort()
        .filter((id) => pref.indexOf(id) < 0),
    );
  const out: Record<string, Route> = {};
  ids.forEach((id) => {
    const d = scens[id],
      k = routeKey(d.missions || []);
    if (!k || out[k]) return;
    out[k] = { ru: k.split(">").map(ptRu).join(" → "), src: id, missions: d.missions, duration: d.duration_s };
  });
  routesFor = scens;
  routesCache = out;
  return out;
}
const firstRoute = () => {
  const R = routes();
  return R["warehouse>shop_a>warehouse"] ? "warehouse>shop_a>warehouse" : Object.keys(R)[0] || "";
};

/* ---------------------------------------------------------------- состояние */
const customs = () => app.get().scenList.filter((s) => s.group === "Свои");
const groupOf = (id: string) => app.get().scenList.find((s) => s.id === id)?.group;

function newState(): Partial<BState> {
  return { peds: [], pallets: [], boxes: [], removed: [], route: firstRoute(), missions: null, duration: null,
    snow: false, fog: [120, 200], fogOn: false, gnss: [0, 0], gnssOn: false,
    name: "Мой сценарий " + (customs().length + 1), id: null, map: null, det: false, generator: null, extraEv: [] }; // prettier-ignore
}

/** Состояние конструктора — изменяемый объект; компоненты подписаны на номер версии. */
export const B: BState = {
  tool: "ped",
  cur: null,
  src: "new",
  ro: false,
  msg: null,
  busy: false,
  ...(newState() as Omit<BState, "tool" | "cur" | "src" | "ro" | "msg" | "busy">),
  fogOn: true,
  name: "Мой сценарий 1",
};
export const builder = createStore({ v: 0, started: false });
export const bump = () => builder.set((s) => ({ v: s.v + 1 }));

const FULL: Record<string, Scenario> = {}; // id -> сценарий целиком (с картой)

export const curMap = (): MapData => B.map || app.get().baseMap;
/** Текущий маршрут. Сценарии могли прийти позже создания состояния: пустой или неизвестный
    маршрут заменяется первым доступным лениво, при каждом обращении. */
export function curRoute(): string {
  if (!B.route || !routes()[B.route]) B.route = firstRoute();
  return B.route;
}
export const curMissions = (): ScenMission[] => B.missions || routes()[curRoute()]?.missions || [];

function loadState(st: Partial<BState>, src: string, ro: boolean) {
  Object.assign(B, JSON.parse(JSON.stringify(st)), { cur: null, src, ro, msg: null });
}

function stateFromScenario(id: string): Partial<BState> {
  const d = FULL[id];
  const fog = d.events.find((e) => e.type === "fog_bank"),
    out = d.events.find((e) => e.type === "gnss_outage");
  const isCustom = groupOf(id) === "Свои";
  return {
    name: isCustom ? d.description || id : scenRu(id, app.get().scenList),
    id: isCustom ? id : null,
    route: routeKey(d.missions),
    missions: d.missions,
    duration: d.duration_s,
    snow: !!(d.weather || {}).snow,
    fogOn: !!fog,
    fog: fog ? [fog.t1 ?? 0, fog.t2 ?? 0] : [120, 200],
    gnssOn: !!out,
    gnss: out ? [out.t1 ?? 0, out.t2 ?? 0] : [0, 0],
    peds: d.pedestrians.map((p) => ({ inatt: !!p.inattentive, pts: p.waypoints, speed: p.speed, t0: p.t_start || 0, loop: p.loop !== false })), // prettier-ignore
    pallets: d.events.filter((e) => e.type === "object_dropped").map((e) => ({ x: e.x ?? 0, y: e.y ?? 0, t: e.t ?? 0, r: e.r ?? 0.4 })), // prettier-ignore
    removed: d.map_patches.filter((q) => q.op === "remove").map((q) => q.id),
    boxes: d.map_patches.filter((q) => q.op === "add").map((q) => ({ poly: q.polygon, id: q.id })),
    map: d.map || null,
    det: !!d.provide_detections,
    generator: d.generator || null,
    // вторые и следующие полосы тумана и окна без спутника: в форме одна строка, остальные сохраняются как есть
    extraEv: d.events.filter((e) => (e.type === "fog_bank" && e !== fog) || (e.type === "gnss_outage" && e !== out)),
  };
}

/** Первый показ конструктора: заготовка, чтобы новый сценарий не был пустым. */
export function startBuilder(): void {
  if (builder.get().started) return;
  B.route = firstRoute();
  B.peds.push({ inatt: false, pts: [[112, 158], [112, 141], [125, 141]], speed: 1.0, t0: 0, loop: true }); // prettier-ignore
  B.peds.push({ inatt: true, pts: [[150, 145], [150, 156], [160, 156]], speed: 1.3, t0: 0, loop: true }); // prettier-ignore
  B.pallets.push({ x: 140, y: 152.2, t: 70, r: 0.4 });
  B.name = "Мой сценарий " + (customs().length + 1);
  builder.set({ started: true });
  const sid = app.get().buildScen;
  if (sid && app.get().scens[sid]) {
    app.set({ buildScen: null });
    void openScenario("sc:" + sid);
  }
}

/** Открыть сценарий из библиотеки: организаторов и проверочные — только просмотр, свои — правка. */
export async function openScenario(v: string): Promise<void> {
  if (v === "new") loadState(newState(), "new", false);
  else {
    const id = v.slice(3);
    try {
      if (!FULL[id]) FULL[id] = (await api.scenario(id)).scenario;
    } catch (e) {
      B.msg = ["bad", "Не удалось открыть сценарий: " + (e as Error).message];
      bump();
      return;
    }
    loadState(stateFromScenario(id), v, groupOf(id) !== "Свои");
  }
  bump();
}

export function makeCopy(): void {
  Object.assign(B, { ro: false, src: "new", id: null, name: "Копия: " + B.name, msg: null });
  bump();
}

export function finishPed(): void {
  if (B.cur && B.cur.pts.length >= 2) B.peds.push(B.cur);
  B.cur = null;
}

export function clickMap(x: number, y: number): void {
  if (B.ro) return;
  const T = B.tool;
  if (T === "ped" || T === "ped_in") {
    if (!B.cur || B.cur.inatt !== (T === "ped_in")) {
      finishPed();
      B.cur = { inatt: T === "ped_in", pts: [], speed: 1.1, t0: 0, loop: true };
    }
    B.cur.pts.push([+x.toFixed(1), +y.toFixed(1)]);
  } else if (T === "pallet") B.pallets.push({ x: +x.toFixed(1), y: +y.toFixed(1), t: 60, r: 0.4 });
  else if (T === "box") B.boxes.push({ x: +x.toFixed(1), y: +y.toFixed(1) });
  else if (T === "remove") {
    const b = curMap().buildings.find((q) => inside(x, y, q.polygon));
    if (b) {
      const i = B.removed.indexOf(b.id);
      if (i >= 0) B.removed.splice(i, 1);
      else B.removed.push(b.id);
    }
  }
  B.msg = null;
  bump();
}

/* ---------------------------------------------------------------- проверки и сборка */
export type Check = ["ok" | "warn" | "dim", string];

export function checks(): Check[] {
  const out: Check[] = [];
  const ms = curMissions();
  if (!ms.length) return [["warn", "Нет ни одного сценария с маршрутом: укажите папку симулятора (SAFEROUTE_SIM)"]];
  out.push(["ok", "Маршрут: " + ms.map((m, i) => (i ? "" : ptRu(m.from) + " → ") + ptRu(m.to)).join(" → ")]);
  out.push([
    B.peds.length ? "ok" : "dim",
    `Пешеходов: ${B.peds.length}, из них невнимательных ${B.peds.filter((p) => p.inatt).length}`,
  ]);
  B.pallets.forEach((p, i) => {
    let dmin = 1e9;
    ms.forEach((m) => {
      const r = m.ref || [];
      for (let k = 1; k < r.length; k++) {
        const [ax, ay] = r[k - 1],
          [bx, by] = r[k];
        const ex = bx - ax,
          ey = by - ay,
          ll = Math.max(ex * ex + ey * ey, 1e-9);
        const u = Math.max(0, Math.min(1, ((p.x - ax) * ex + (p.y - ay) * ey) / ll));
        dmin = Math.min(dmin, Math.hypot(ax + u * ex - p.x, ay + u * ey - p.y));
      }
    });
    if (dmin < 1.25)
      out.push([
        "warn",
        `Поддон ${i + 1} почти на оси пути (${dmin.toFixed(1)} м). Организаторы такие сценарии отсеивают: эталонный контроллер их не проходит.`,
      ]);
    else if (dmin < 3)
      out.push(["ok", `Поддон ${i + 1} у самого пути (${dmin.toFixed(1)} м от оси) — как в скрытых сценариях`]);
    else out.push(["dim", `Поддон ${i + 1} далеко от пути (${dmin.toFixed(1)} м) — на тележку не повлияет`]);
  });
  if (B.fogOn)
    out.push(
      B.fog[0] < B.fog[1]
        ? ["ok", `Туман ${B.fog[0]}–${B.fog[1]} с: лидар видит 6 м`]
        : ["warn", "Туман: начало должно быть раньше конца"],
    );
  if (B.gnssOn)
    out.push(
      B.gnss[0] < B.gnss[1]
        ? ["ok", `Пропадание спутника ${B.gnss[0]}–${B.gnss[1]} с`]
        : ["warn", "Нет спутника: начало должно быть раньше конца"],
    );
  if (B.snow) out.push(["ok", "Снег весь прогон: ложные отражения лидара"]);
  const extra = B.extraEv || [];
  if (extra.length)
    out.push([
      "ok",
      "Из исходного сценария сохраняются ещё: " +
        extra.map((e) => (e.type === "fog_bank" ? "туман " : "нет спутника ") + e.t1 + "–" + e.t2 + " с").join(", "),
    ]);
  if (B.cur && B.cur.pts.length < 2) out.push(["dim", "Пешеход с одной точкой пути не сохранится — поставьте вторую"]);
  return out;
}

/** Сценарий amr-1.0 из состояния конструктора. */
export function buildScenario(): Record<string, unknown> {
  finishPed();
  const map = curMap(),
    pts = map.points;
  const ms = curMissions();
  const missions = ms.map((m, i) => {
    const ref = m.ref;
    let L = 0;
    for (let k = 1; k < ref.length; k++) L += Math.hypot(ref[k][0] - ref[k - 1][0], ref[k][1] - ref[k - 1][1]);
    const deadline = m.deadline_s || +((L / 1.39) * 1.6).toFixed(1);
    return {
      id: "m" + (i + 1),
      from: m.from,
      to: m.to,
      deadline_s: deadline,
      reference_path: ref,
      reference_length_m: m.reference_length_m != null ? m.reference_length_m : +L.toFixed(3),
    };
  });
  const sumDl = missions.reduce((a, m) => a + m.deadline_s, 0);
  const R = routes()[curRoute()];
  const duration = B.duration || (R && !B.missions ? R.duration : 0) || Math.round(sumDl + 15);
  const ev: SimEvent[] = [];
  if (B.fogOn && B.fog[0] < B.fog[1]) ev.push({ type: "fog_bank", t1: B.fog[0], t2: B.fog[1] });
  if (B.gnssOn && B.gnss[0] < B.gnss[1]) ev.push({ type: "gnss_outage", t1: B.gnss[0], t2: B.gnss[1] });
  (B.extraEv || []).forEach((e) => ev.push({ ...e }));
  B.pallets.forEach((p) => ev.push({ type: "object_dropped", t: p.t, x: p.x, y: p.y, r: p.r || 0.4 }));
  // id патчей: исходные сохраняются, новым — BOX_n, не совпадающий со зданиями и другими патчами
  const taken = new Set(
    map.buildings.map((b) => b.id).concat(B.boxes.map((b) => b.id || "").filter(Boolean), B.removed),
  );
  let nb = 0;
  const freeId = () => {
    while (taken.has("BOX_" + ++nb));
    return "BOX_" + nb;
  };
  const patches = B.boxes
    .map((b) => {
      const x = b.x ?? 0,
        y = b.y ?? 0;
      const polygon = b.poly || [[x - 3, y - 1.25], [x + 3, y - 1.25], [x + 3, y + 1.25], [x - 3, y + 1.25]]; // prettier-ignore
      return { id: b.id || freeId(), op: "add", polygon } as Record<string, unknown>;
    })
    .concat(B.removed.map((id) => ({ id, op: "remove" })));
  const p0 = missions.length ? pts[missions[0].from] : null;
  const th = p0 ? Math.atan2(Math.sin(p0.heading + Math.PI), Math.cos(p0.heading + Math.PI)) : 0;
  const sc: Record<string, unknown> = {
    schema: "amr-1.0", name: B.id || "custom", description: B.name, dt: 0.1, duration_s: duration, hidden: false,
    provide_detections: !!B.det, weather: { snow: B.snow }, map, map_patches: patches,
    start: p0 ? { x: p0.x, y: p0.y, theta: +th.toFixed(6) } : { x: 0, y: 0, theta: 0 },
    missions,
    pedestrians: B.peds.map((p, i) => ({ id: "p" + (i + 1), waypoints: p.pts, speed: p.speed, inattentive: p.inatt, loop: p.loop !== false, t_start: p.t0 || 0 })),
    events: ev,
  }; // prettier-ignore
  if (B.generator) sc.generator = B.generator; // происхождение копии скрытоподобного сценария
  return sc;
}

/* Токены правки своих сценариев: сервер перезаписывает сценарий, только если предъявлен токен,
   выданный при его первом сохранении в этом браузере. */
const TOKENS_KEY = "saferoute.customTokens";
function tokens(): Record<string, string> {
  try {
    return JSON.parse(localStorage.getItem(TOKENS_KEY) || "{}") as Record<string, string>;
  } catch {
    return {};
  }
}
function keepToken(id: string, token: string): void {
  try {
    localStorage.setItem(TOKENS_KEY, JSON.stringify({ ...tokens(), [id]: token }));
  } catch {
    /* без localStorage следующая правка сохранится как новый сценарий */
  }
}

/** Сохранить в «Свои» (сервер проверяет сценарий схемой симулятора). */
export async function saveCustom(): Promise<string> {
  B.busy = true;
  B.msg = null;
  bump();
  try {
    const asked = B.id;
    const r = await api.saveScenario(asked, asked ? tokens()[asked] || null : null, buildScenario());
    keepToken(r.id, r.token);
    const d = await api.scenario(r.id);
    FULL[r.id] = d.scenario;
    const { map: _map, generator: _gen, ...summary } = d.scenario;
    void _map;
    void _gen;
    app.set((s) => {
      const scenList = s.scenList.some((q) => q.id === r.id)
        ? s.scenList.map((q) => (q.id === r.id ? { ...q, title: B.name, scenario: summary } : q))
        : [...s.scenList, { id: r.id, group: "Свои" as const, title: B.name, scenario: summary }];
      return { scenList, scens: { ...s.scens, [r.id]: summary } };
    });
    Object.assign(B, {
      id: r.id,
      src: "sc:" + r.id,
      msg: [
        "ok",
        asked && asked !== r.id
          ? `Сохранено как новый: «${B.name}» (${r.id}) — ${asked} создан в другом браузере и не перезаписывается. Симулятор принял сценарий.`
          : `Сохранено: «${B.name}» (${r.id}). Симулятор принял сценарий.`,
      ],
    });
    return r.id;
  } catch (e) {
    B.msg = ["bad", (e as Error).message];
    throw e;
  } finally {
    B.busy = false;
    bump();
  }
}

/** Скачать JSON: в просмотре — исходный файл как есть, иначе — собранный сценарий. */
export async function scenarioBlob(): Promise<{ blob: Blob; name: string }> {
  const name = (B.ro ? B.src.slice(3) : B.id || "custom_scenario") + ".json";
  if (B.ro) {
    const r = await fetch(api.scenarioRawUrl(B.src.slice(3)));
    if (!r.ok) throw new Error("сценарий не найден на сервере (" + r.status + ")");
    return { blob: await r.blob(), name };
  }
  return { blob: new Blob([JSON.stringify(buildScenario(), null, 1)], { type: "application/json" }), name };
}

/* ---------------------------------------------------------------- рисование поверх карты */
export function overlay(
  ctx: CanvasRenderingContext2D,
  X: (x: number) => number,
  Y: (y: number) => number,
  sc: number,
  bad: string,
  warn: string,
): void {
  curMissions().forEach((m) => {
    const ref = m.ref;
    if (!ref || !ref.length) return;
    ctx.beginPath();
    ref.forEach(([x, y], k) => (k ? ctx.lineTo(X(x), Y(y)) : ctx.moveTo(X(x), Y(y))));
    ctx.strokeStyle = "rgba(74,140,255,0.55)";
    ctx.lineWidth = 3;
    ctx.setLineDash([8, 6]);
    ctx.stroke();
    ctx.setLineDash([]);
  });
  B.removed.forEach((id) => {
    const b = curMap().buildings.find((q) => q.id === id);
    if (!b) return;
    ctx.beginPath();
    b.polygon.forEach(([x, y], k) => (k ? ctx.lineTo(X(x), Y(y)) : ctx.moveTo(X(x), Y(y))));
    ctx.closePath();
    ctx.fillStyle = "rgba(11,13,17,0.75)";
    ctx.fill();
    ctx.strokeStyle = bad;
    ctx.setLineDash([4, 3]);
    ctx.lineWidth = 1.5;
    ctx.stroke();
    ctx.setLineDash([]);
  });
  B.boxes.forEach((bx) => {
    ctx.fillStyle = "rgba(196,89,90,0.3)";
    ctx.strokeStyle = bad;
    ctx.lineWidth = 1.5;
    if (bx.poly) {
      ctx.beginPath();
      bx.poly.forEach(([x, y], k) => (k ? ctx.lineTo(X(x), Y(y)) : ctx.moveTo(X(x), Y(y))));
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
    } else {
      const x = bx.x ?? 0,
        y = bx.y ?? 0;
      ctx.fillRect(X(x - 3), Y(y + 1.25), 6 * sc, 2.5 * sc);
      ctx.strokeRect(X(x - 3), Y(y + 1.25), 6 * sc, 2.5 * sc);
    }
  });
  B.pallets.forEach((p) => {
    ctx.beginPath();
    ctx.arc(X(p.x), Y(p.y), Math.max(4, (p.r || 0.4) * sc), 0, Math.PI * 2);
    ctx.fillStyle = "#8a6b3f";
    ctx.fill();
    ctx.strokeStyle = warn;
    ctx.lineWidth = 1.5;
    ctx.stroke();
    ctx.font = "500 10px JetBrains Mono, monospace";
    ctx.fillStyle = warn;
    ctx.textAlign = "left";
    ctx.fillText("t=" + p.t + " с", X(p.x) + 8, Y(p.y) - 6);
  });
  B.peds.concat(B.cur ? [B.cur] : []).forEach((pd) => {
    const col = pd.inatt ? bad : "#e8eaed";
    ctx.beginPath();
    pd.pts.forEach(([x, y], k) => (k ? ctx.lineTo(X(x), Y(y)) : ctx.moveTo(X(x), Y(y))));
    ctx.strokeStyle = pd.inatt ? "rgba(196,89,90,0.7)" : "rgba(232,234,237,0.6)";
    ctx.lineWidth = 1.5;
    ctx.setLineDash(pd === B.cur ? [4, 3] : []);
    ctx.stroke();
    ctx.setLineDash([]);
    pd.pts.forEach(([x, y], k) => {
      ctx.beginPath();
      ctx.arc(X(x), Y(y), k ? 3 : 5, 0, Math.PI * 2);
      ctx.fillStyle = col;
      ctx.fill();
    });
  });
}
