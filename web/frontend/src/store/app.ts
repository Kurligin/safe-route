/* Состояние приложения и действия: данные с сервера, выбор прогона, вкладки, очередь прогонов. */
import { api } from "../api/client";
import type { Job, MapData, Meta, ReadyRun, Run, Scenario, ScenItem } from "../api/types";
import { derive, isReady, pairFor, runOrder } from "../lib/derive";
import { createStore, useStore } from "./createStore";

export type Tab = "run" | "cmp" | "launch" | "build";
export type Mode = "run" | "cmp";
export type LayerKey = "zones" | "trail" | "est" | "peds" | "path" | "patches";

export interface LaunchForm {
  scen: string[];
  ctrl: string[];
  seeds: string;
  jobIds: string[];
  running: boolean;
  finished: boolean;
  error: string;
}

/** Одиночный запуск из панели прогона: «заново с seed» (primary) или пара для сравнения (compare). */
export interface OpenJob {
  id: string | null;
  role: "primary" | "compare";
  error: string;
}

export interface AppState {
  status: "loading" | "ready" | "error";
  loadError: string;
  meta: Meta;
  runs: Record<string, Run>;
  order: string[];
  scenList: ScenItem[];
  scens: Record<string, Scenario>;
  baseMap: MapData;
  primary: string | null;
  compare: string | null;
  tab: Tab;
  lastMode: Mode;
  playing: boolean;
  speed: number;
  follow: boolean;
  layers: Record<LayerKey, boolean>;
  jobs: Record<string, Job>;
  launch: LaunchForm;
  openJob: OpenJob | null;
  panelError: string;
  buildScen: string | null; // сценарий, который конструктор откроет при первом показе (из адреса)
  showLimits: boolean; // показывать прогоны витрины «граница возможностей»
}

const LIMITS_KEY = "saferoute.showLimits";
function storedShowLimits(): boolean {
  try {
    return localStorage.getItem(LIMITS_KEY) === "1";
  } catch {
    return false;
  }
}

export function setShowLimits(on: boolean): void {
  app.set({ showLimits: on });
  try {
    localStorage.setItem(LIMITS_KEY, on ? "1" : "0");
  } catch {
    /* только на эту сессию */
  }
}

/** Прогоны для списков: ограничения скрыты, пока не включён переключатель; выбранные видны всегда. */
export function visibleKeys(keys: string[], s: AppState): string[] {
  if (s.showLimits) return keys;
  return keys.filter((k) => !s.runs[k]?.limit || k === s.primary || k === s.compare);
}

const EMPTY_MAP: MapData = { bounds: [0, 0, 250, 200], drivable: [], buildings: [], points: {}, zones: [] };

export const app = createStore<AppState>({
  status: "loading",
  loadError: "",
  meta: { canRun: false, readonly: false, reason: "сервер не ответил", parallel: 2, avgS: 6, controllers: [] },
  runs: {},
  order: [],
  scenList: [],
  scens: {},
  baseMap: EMPTY_MAP,
  primary: null,
  compare: null,
  tab: "run",
  lastMode: "run",
  playing: false,
  speed: 4,
  follow: false,
  layers: { zones: true, trail: true, est: true, peds: true, path: true, patches: true },
  jobs: {},
  launch: { scen: [], ctrl: [], seeds: "1, 2, 3", jobIds: [], running: false, finished: false, error: "" },
  openJob: null,
  panelError: "",
  buildScen: null,
  showLimits: storedShowLimits(),
});

/** Время проигрывания — отдельный store: меняется каждый кадр, подписываются только холсты и «Сейчас». */
export const clock = createStore({ t: 0 });

export const useApp = <U>(sel: (s: AppState) => U): U => useStore(app, sel);
export const useClock = (): number => useStore(clock, (s) => s.t);

/* ---------------------------------------------------------------- время */
export function readyRun(key: string | null | undefined): ReadyRun | null {
  const R = key ? app.get().runs[key] : undefined;
  return isReady(R) ? R : null;
}

export function derived(R: ReadyRun) {
  const s = app.get();
  return derive(R, s.baseMap, s.scens);
}

export function tMax(): number {
  const s = app.get();
  const a = readyRun(s.primary),
    b = readyRun(s.compare);
  return Math.max(a ? derived(a).tEnd : 0, b ? derived(b).tEnd : 0) || 1;
}

export function seek(t: number, pause: boolean): void {
  clock.set({ t: Math.max(0, Math.min(tMax(), t)) });
  if (pause && app.get().playing) app.set({ playing: false });
}

/* ---------------------------------------------------------------- прогоны */
const loading: Record<string, Promise<void>> = {};

/** Подгрузить тики прогона (один раз; параллельные вызовы ждут один запрос). */
export function ensureFull(key: string | null): Promise<void> {
  const R = key ? app.get().runs[key] : undefined;
  if (!key || !R || isReady(R)) return Promise.resolve();
  if (!loading[key]) {
    loading[key] = api
      .run(key)
      .then((d) => {
        app.set((s) => ({ runs: { ...s.runs, [key]: { ...s.runs[key], ...d } } }));
      })
      .finally(() => delete loading[key]);
  }
  return loading[key];
}

/** Выбрать прогон (и пару в режиме сравнения), подгрузить тики. */
export async function openRun(key?: string | null, mode?: Mode): Promise<void> {
  const s = app.get();
  const patch: Partial<AppState> = { panelError: "" };
  const primary = key && s.runs[key] ? key : s.primary;
  patch.primary = primary;
  const tab = mode || s.tab;
  if (mode) patch.tab = mode;
  if (tab === "cmp" && primary) {
    const c = s.compare;
    if (!c || c === primary || !s.runs[c] || s.runs[c].scenario !== s.runs[primary].scenario)
      patch.compare = pairFor(primary, s.order, s.runs);
  }
  app.set(patch);
  const st = app.get();
  try {
    await Promise.all([ensureFull(st.primary), st.tab === "cmp" ? ensureFull(st.compare) : null]);
  } catch (e) {
    app.set({ panelError: "Не удалось загрузить прогон: " + (e as Error).message });
    return;
  }
  clock.set({ t: Math.min(clock.get().t, tMax()) });
}

/** Выбор другого прогона или режима: время в начало, проигрывание на паузу. */
function resetTime(): void {
  clock.set({ t: 0 });
  if (app.get().playing) app.set({ playing: false });
}

/** Сменить прогон для сравнения («Сравнить с»). */
export function selectCompare(key: string): void {
  app.set({ compare: key });
  resetTime();
  void openRun();
}

/** Клик по прогону в списке. */
export function selectRun(key: string): void {
  const s = app.get();
  let compare = s.compare;
  if (compare && (compare === key || s.runs[compare].scenario !== s.runs[key].scenario))
    compare = s.tab === "cmp" ? pairFor(key, s.order, s.runs) : null;
  app.set({ primary: key, compare });
  resetTime();
  void openRun();
}

export function setTab(tab: Tab): void {
  if (tab === "launch" || tab === "build") {
    app.set({ tab, playing: false });
    return;
  }
  app.set(tab === "run" ? { tab, compare: null } : { tab });
  void openRun();
}

export function setMode(mode: Mode): void {
  app.set({ lastMode: mode });
  resetTime();
  setTab(mode);
}

/** «Открыть» / «Сравнить» из очереди и истории. */
export function openFromLaunch(key: string, mode: Mode): void {
  app.set({ primary: key, compare: null, lastMode: mode });
  resetTime();
  setTab(mode);
}

/* ---------------------------------------------------------------- очередь прогонов */
const handled = new Set<string>(); // завершённые задания, чей прогон уже подгружен
let pollTimer: ReturnType<typeof setTimeout> | null = null;

async function addRun(key: string): Promise<void> {
  const d = await api.runLite(key); // перезапуск с тем же seed заменяет старый прогон
  app.set((s) => {
    const runs = { ...s.runs, [key]: d };
    return { runs, order: runOrder(runs, s.scenList) };
  });
}

async function poll(): Promise<void> {
  pollTimer = null;
  let list: Job[] | null = null;
  try {
    list = await api.jobs();
  } catch {
    list = null;
  }
  const fresh: Job[] = [];
  if (list) {
    const jobs = { ...app.get().jobs };
    list.forEach((j) => (jobs[j.id] = j));
    for (const j of list) {
      if (j.state === "done" && j.key && !handled.has(j.id)) {
        handled.add(j.id);
        try {
          await addRun(j.key);
          fresh.push(j);
        } catch (e) {
          jobs[j.id] = { ...j, state: "error", error: (e as Error).message };
        }
      } else if (j.state === "error") handled.add(j.id);
    }
    app.set({ jobs });
  }
  afterPoll(fresh);
  const active = Object.values(app.get().jobs).some((j) => j.state === "queued" || j.state === "run");
  if (active || !list) pollTimer = setTimeout(poll, list ? 300 : 1500);
}

function afterPoll(fresh: Job[]): void {
  const s = app.get();
  // одиночный запуск из панели прогона: готовый прогон открывается сам
  const oj = s.openJob;
  if (oj && oj.id) {
    const j = s.jobs[oj.id];
    if (j && fresh.some((f) => f.id === j.id)) {
      app.set({ openJob: null });
      if (s.tab === "run" || s.tab === "cmp") {
        if (oj.role === "compare") app.set({ compare: j.key || null });
        else {
          app.set({ primary: j.key || null });
          clock.set({ t: 0 });
        }
        void openRun();
      }
    }
  }
  // новые прогоны: если список был пуст — показать первый; заменённые перезапуском — перечитать
  if (fresh.length) {
    const st = app.get();
    const wasEmpty = !st.primary;
    if (wasEmpty && st.order.length) app.set({ primary: st.order[0] });
    if (
      (st.tab === "run" || st.tab === "cmp") &&
      (wasEmpty || fresh.some((j) => j.key === st.primary || j.key === st.compare))
    )
      void openRun();
  }
  // пачка из вкладки «Запуск» завершилась
  const L = app.get().launch;
  if (L.running && L.jobIds.length) {
    const jobs = L.jobIds.map((id) => app.get().jobs[id]).filter(Boolean);
    if (jobs.length === L.jobIds.length && jobs.every((j) => j.state === "done" || j.state === "error"))
      app.set({ launch: { ...L, running: false, finished: true } });
  }
}

function startPolling(): void {
  if (!pollTimer) pollTimer = setTimeout(poll, 60);
}

export async function launchJobs(scenario: string, controllers: string[], seeds: number[]): Promise<string[]> {
  const r = await api.launch(scenario, controllers, seeds);
  const jobs = { ...app.get().jobs };
  r.jobs.forEach((id) => {
    if (!jobs[id]) jobs[id] = { id, scenario, state: "queued", p: 0 };
    handled.delete(id);
  });
  app.set({ jobs });
  startPolling();
  return r.jobs;
}

export const parseSeeds = (t: string): number[] => [
  ...new Set(
    t
      .split(/[ ,;]+/)
      .map((x) => parseInt(x, 10))
      .filter((x) => x >= 0),
  ),
];

/** Запуск пачки из вкладки «Запуск»: по запросу на сценарий. */
export async function startBatch(): Promise<void> {
  const s = app.get();
  const L = s.launch;
  const seeds = parseSeeds(L.seeds);
  const scen = s.scenList.map((q) => q.id).filter((id) => L.scen.includes(id));
  const ctrls = s.meta.controllers.map((c) => c.key).filter((k) => L.ctrl.includes(k));
  const ids: string[] = [];
  app.set({ launch: { ...L, jobIds: [], running: true, finished: false, error: "" } });
  try {
    for (const sc of scen) {
      ids.push(...(await launchJobs(sc, ctrls, seeds)));
      app.set((st) => ({ launch: { ...st.launch, jobIds: [...ids] } }));
    }
  } catch (e) {
    app.set((st) => ({
      launch: { ...st.launch, error: "Запуск не принят: " + (e as Error).message, running: ids.length > 0 },
    }));
  }
}

/** Один прогон из панели: «Прогнать заново с seed» или «Запустить» пару для сравнения. */
export async function runOne(scenario: string, ctrl: string, seed: number, role: "primary" | "compare"): Promise<void> {
  app.set({ openJob: { id: null, role, error: "" } });
  try {
    const ids = await launchJobs(scenario, [ctrl], [seed]);
    app.set({ openJob: { id: ids[0], role, error: "" } });
  } catch (e) {
    app.set({ openJob: { id: null, role, error: (e as Error).message } });
  }
}

/* ---------------------------------------------------------------- старт */
export async function init(): Promise<void> {
  try {
    const [meta, runs, sc] = await Promise.all([api.meta(), api.runs(), api.scenarios()]);
    const scens: Record<string, Scenario> = {};
    sc.items.forEach((q) => (scens[q.id] = q.scenario));
    const order = runOrder(runs, sc.items);
    // ссылка вида #run=<id>&t=62&mode=cmp&cmp=<id>, #tab=launch или #tab=build&scen=<id>
    const hp = new URLSearchParams(location.hash.replace(/^#/, ""));
    const pick = hp.get("run");
    const primary = pick && runs[pick] ? pick : runs["04_busy_yard__s1"] ? "04_busy_yard__s1" : order[0] || null;
    const cmp = hp.get("cmp");
    const mode: Mode = hp.get("mode") === "cmp" ? "cmp" : "run";
    const has = (id: string) => sc.items.some((q) => q.id === id);
    app.set({
      status: "ready",
      meta,
      runs,
      order,
      scenList: sc.items,
      scens,
      baseMap: sc.baseMap || EMPTY_MAP,
      primary,
      compare: cmp && runs[cmp] ? cmp : null,
      lastMode: mode,
      launch: {
        ...app.get().launch,
        scen: ["02_gnss_shadow", "04_busy_yard"].filter(has),
        ctrl: meta.controllers.map((c) => c.key),
      },
      buildScen: hp.get("scen"),
    });
    clock.set({ t: +(hp.get("t") || 0) || 0 });
    const tab = hp.get("tab");
    if (tab === "launch" || tab === "build") setTab(tab);
    else if (mode === "cmp") {
      app.set({ tab: "cmp" });
      void openRun();
    } else setTab("run");
  } catch (e) {
    app.set({ status: "error", loadError: (e as Error).message });
    return;
  }
  // задания, начатые до перезагрузки страницы, показываем в очереди
  try {
    const list = await api.jobs();
    const jobs: Record<string, Job> = {};
    list.forEach((j) => {
      jobs[j.id] = j;
      if (j.state === "done" || j.state === "error") handled.add(j.id);
    });
    const active = list.filter((j) => j.state === "queued" || j.state === "run").map((j) => j.id);
    app.set({ jobs });
    if (active.length) {
      app.set((s) => ({ launch: { ...s.launch, jobIds: active, running: true } }));
      startPolling();
    }
  } catch {
    /* очередь недоступна — покажем пустую */
  }
}
