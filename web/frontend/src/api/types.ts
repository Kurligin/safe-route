/* Формы данных API бэкенда (backend/saferoute/api.py). */

export type Pt = [number, number];
export type Polygon = Pt[];

export interface MapPoint {
  x: number;
  y: number;
  heading: number;
  tol?: number;
}

export interface Zone {
  id?: string;
  type: "gnss_shadow" | "people_area" | "speed_limit" | "forbidden" | string;
  polygon: Polygon;
  v_max?: number;
}

export interface Building {
  id: string;
  polygon: Polygon;
}

export interface MapData {
  bounds: number[];
  drivable: Polygon[];
  buildings: Building[];
  points: Record<string, MapPoint>;
  zones: Zone[];
  [k: string]: unknown;
}

export interface MapPatch {
  id: string;
  op: "add" | "remove";
  polygon?: Polygon;
}

export interface SimEvent {
  type: "fog_bank" | "gnss_outage" | "object_dropped" | string;
  t?: number;
  t1?: number;
  t2?: number;
  x?: number;
  y?: number;
  r?: number;
  [k: string]: unknown;
}

export interface MissionRecord {
  id: string;
  from: string;
  to: string;
  t_start: number;
  t_end: number;
  t_arrival: number | null;
  deadline_s: number;
  delivered: boolean;
  reason: string;
}

export interface MissionHeader {
  id: string;
  from: string;
  to: string;
  deadline_s?: number;
}

export interface Episode {
  type: string;
  t_start: number;
  t_end: number;
  cost?: number;
  x?: number;
  y?: number;
}

export type BlockKey = "delivery" | "efficiency" | "safety" | "rules" | "pose" | "collisions";

export interface Score {
  total: number;
  blocks: Partial<Record<BlockKey, number>>;
  max: Partial<Record<BlockKey, number>>;
  deliveries: number;
  fatal: boolean;
  episodes: Episode[];
}

export type Num = number | null;

export interface Ticks {
  t: number[];
  x: number[];
  y: number[];
  th: number[];
  px: Num[];
  py: Num[];
  pth: Num[];
  v: number[];
  cv: Num[];
  w: Num[];
  st: string[];
  nt: string[];
  m: (string | null)[];
  hum: Num[];
  obj: Num[];
  vmax: Num[];
  err: Num[];
  peds: Pt[][];
  coll: number[];
  cont: number[];
  drv: number[];
}

export interface Stop {
  t0: number;
  t1: number;
  reason: string;
  full: boolean;
  x: number;
  y: number;
}

/** Прогон: сводка всегда, тики/карта/остановки — после подгрузки по требованию. */
export interface Run {
  ctrl: "ours" | "baseline";
  label: string;
  scenario: string;
  seed: number;
  points: Record<string, MapPoint>;
  events: SimEvent[];
  patches: MapPatch[];
  missions_hdr: MissionHeader[];
  missions: MissionRecord[];
  n_ticks: number;
  score: Score;
  step_ms: { mean: number; max: number };
  wall_s: number;
  mtime: number;
  limit?: boolean; // витрина «граница возможностей»: в списках скрыта по умолчанию
  map?: MapData | null;
  ticks?: Ticks;
  stops?: Stop[];
}

export type ReadyRun = Run & { ticks: Ticks; stops: Stop[] };

export interface ScenMission {
  id: string;
  from: string;
  to: string;
  deadline_s: number | null;
  reference_length_m: number | null;
  ref: Pt[];
}

export interface Pedestrian {
  id?: string;
  waypoints: Pt[];
  speed: number;
  inattentive?: boolean;
  loop?: boolean;
  t_start?: number;
}

export interface Scenario {
  name: string;
  description: string;
  duration_s: number | null;
  provide_detections: boolean;
  generator?: unknown;
  weather: { snow?: boolean; [k: string]: unknown };
  start: { x: number; y: number; theta: number } | null;
  missions: ScenMission[];
  pedestrians: Pedestrian[];
  events: SimEvent[];
  map_patches: MapPatch[];
  map?: MapData | null;
}

export type Group = "Открытые" | "Учебные" | "Скрытоподобные" | "Стресс" | "Проверочные" | "Витрина" | "Свои";

export interface ScenItem {
  id: string;
  group: Group;
  title: string;
  limit?: boolean;
  scenario: Scenario;
}

export interface Meta {
  canRun: boolean;
  readonly: boolean;
  reason: string;
  parallel: number;
  avgS: number;
  controllers: { key: "ours" | "baseline"; label: string }[];
}

export type JobState = "queued" | "run" | "done" | "error";

export interface Job {
  id: string;
  scenario: string;
  controller?: string;
  label?: string;
  seed?: number;
  state: JobState;
  key?: string | null;
  total?: number | null;
  error?: string | null;
  cmd?: string | null;
  p?: number;
  left?: number;
}
