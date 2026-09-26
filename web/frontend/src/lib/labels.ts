/* Подписи по-русски: сценарии, точки, здания, коды причин, эпизоды, статусы, подсказки «?». */
import type { Group, ScenItem } from "../api/types";

const SCEN_RU: Record<string, string> = {
  "01_clear": "Ясная погода",
  "01e_clear_easy": "Ясная погода (учебный)",
  "02_gnss_shadow": "Тень ГНСС",
  "02e_gnss_shadow_easy": "Тень ГНСС (учебный)",
  "03_fog_snow": "Туман и снег",
  "04_busy_yard": "Оживлённый двор",
  own_pallet_drop: "Поддон у оси дороги",
  own_pickup_first: "Старт не в доке",
  w1_gnss_shadow_126: "Витрина: тень ГНСС 126 м до дока A",
  w2_fog_snow_outage: "Витрина: туман, снег и нет спутника",
  w3_inattentive_crowd: "Витрина: четверо невнимательных в тумане",
  w4_pallet_bypass: "Витрина: объезд поддона",
  w5_map_mismatch: "Витрина: карта расходится с миром",
  w6_estop_pallet: "Витрина: аварийный стоп перед поддоном",
  w7_pickup_first: "Витрина: сначала забор на складе",
  l1_pallet_axis_drop: "Витрина: поддон на оси перед платформой",
  l2_person_by_pallet: "Витрина: человек вплотную к поддону",
  l3_person_turns_ahead: "Витрина: попутный пешеход разворачивается",
  l4_canopy_two_inattentive: "Витрина: двое невнимательных под навесом",
  l5_long_fence_in_fog: "Витрина: длинный забор в тумане",
  l6_blind_run: "Витрина: попытка потерять позу",
};
const numOf = (id: string): string => (id.match(/_(\d{2,})(?:_|$)/) || [])[1] || id.split("_").pop() || id;

/** Название сценария по-русски; для своих — описание из конструктора. */
export function scenRu(id: string, list: ScenItem[]): string {
  if (SCEN_RU[id]) return SCEN_RU[id];
  const s = list.find((q) => q.id === id);
  if (s && s.title) return s.title;
  if (id.indexOf("gen_") === 0) return "Скрытоподобный №" + numOf(id);
  if (id.indexOf("stress_pallet") === 0) return "Поддон у оси №" + numOf(id);
  if (id.indexOf("stress_swarm") === 0) return "Толпа невнимательных №" + numOf(id);
  if (id.indexOf("stress_fog") === 0) return "Туман на северной дороге №" + numOf(id);
  if (id.indexOf("stress_") === 0) return "Стресс №" + numOf(id);
  return id;
}

/** Название прогона в списках: демо потери ориентации (прогон inject_*) — отдельной подписью. */
export function runTitle(key: string, scenario: string, list: ScenItem[]): string {
  if (key.indexOf("inject_") === 0) return "Потеря ориентации (демо)";
  return scenRu(scenario, list);
}

export const PT_RU: Record<string, string> = {
  warehouse: "Склад",
  shop_a: "Цех A",
  shop_b: "Цех B",
  charger: "Зарядка",
};
export const ptRu = (p: string): string => PT_RU[p] || p;
export const DOCK_RU: Record<string, string> = {
  warehouse: "Док склада",
  shop_a: "Док цеха A",
  shop_b: "Док цеха B",
  charger: "Зарядка",
};
export const BUILD_RU: Record<string, string> = {
  W: "Склад",
  A: "Цех A",
  B: "Цех B",
  T: "Высокий корпус T",
  S: "Корпус S",
  N1: "Корпус N1",
};
export const buildRu = (id: string): string =>
  BUILD_RU[id] ||
  ({ K1: "Киоск", FENCE_W: "Забор" } as Record<string, string>)[id] ||
  (/^CAN_\d+$/.test(id) ? "Опора навеса " + id.slice(4) : /_bay_/.test(id) ? "Стенка дока " + id : id);

export const TIP: Record<string, string> = {
  "Наш контроллер":
    "Позиция считается по колёсам и гироскопу и уточняется лидаром по карте стен и спутником (фильтр Калмана). Так же работает реальная машина.",
  Baseline:
    "Пример контроллера от организаторов: колёса + спутник, без привязки к карте по лидару. Теряется в тени ГНСС.",
};
export const SCORE_TIP =
  "Счёт симулятора за один прогон, 0–100. Доставка — до 40 (доля доставленных рейсов), эффективность — до 15 (быстрота относительно эталона), безопасность — до 25 (дистанция до людей), правила — до 10 (дороги, запретные и скоростные зоны), честность позы — до 10 (ошибка оценки позиции меньше 1 м, статусы совпадают с движением). Каждый удар −30. Наезд на человека в движении или ни одной доставки — 0 за сценарий.";
export const SEED_TIP =
  "Seed задаёт случайный шум датчиков и поведение людей. Тот же сценарий с другим seed — те же маршруты, но другие помехи. Жюри гоняет на своих seed, поэтому устойчивость на разных seed важна.";
export const CHECK_TIP =
  "Быстрая проверка по тем же правилам, по которым организаторы допускают скрытые сценарии. При сохранении сценарий дополнительно проверяет сам симулятор.";

export const GROUPS: Group[] = ["Открытые", "Учебные", "Скрытоподобные", "Стресс", "Проверочные", "Витрина", "Свои"];
export const SCEN_TIP: Record<Group, string> = {
  Открытые: "Четыре сценария организаторов. На них жюри гоняет контроллер с новыми seed (критерий Т2).",
  Учебные: "Копии 01 и 02, где симулятор подсказывает положение людей. В скрытых сценариях такой подсказки нет.",
  Скрытоподобные:
    "Наши сценарии, собранные генератором по описанию скрытых сценариев и отобранные тем же правилом, что у организаторов (эталон набирает больше 85).",
  Стресс:
    "Наши сценарии жёстче скрытых: поддон почти на оси дороги, толпа невнимательных пешеходов. Проверка запаса прочности.",
  Проверочные: "Наши сценарии на отдельные случаи: поддон у оси дороги, старт не в доке.",
  Витрина:
    "Сценарии витрины: где решение работает (w1–w7) и где его граница (l1–l6). Подробности — results/showcase/README.md.",
  Свои: "Сценарии, собранные во вкладке «Конструктор».",
};

const CODE_RU: Record<string, string> = {
  "wait:person": "ждёт человека",
  "slow:person": "человек рядом",
  "wait:object": "препятствие впереди",
  "slow:object": "узкий проход",
  "bypass:object": "объезд препятствия",
  "estop:object": "аварийный стоп",
  "mismatch:map": "карта расходится с миром",
  lost: "потеря позиции",
  dock: "заход в док",
  pickup: "едет к точке забора",
  err: "ошибка шага",
  "person near": "человек рядом",
  "too close": "слишком близко",
  "obstacle ahead": "препятствие впереди",
  waiting: "ожидание",
};
export const EP_RU: Record<string, string> = {
  person_near_fast: "человек ближе 3 м на ходу",
  person_close_pass: "проезд ближе 0,5 м к человеку",
  person_contact_moving: "наезд на человека",
  person_contact_standing: "контакт со стоящей платформой",
  out_of_drivable: "выезд за проезд",
  forbidden_zone: "въезд в запретную зону",
  overspeed: "превышение скорости зоны",
  pose_error: "ошибка позы больше 1 м",
  status_mismatch: "статус не совпадает с движением",
  estop_no_object: "аварийный стоп без причины",
  collision: "столкновение",
};
export const ST_RU: Record<string, string> = {
  moving: "едет",
  arrived: "прибыл",
  waiting: "ждёт",
  lost: "потерял позицию",
  estop: "аварийный стоп",
};
export const REASON_RU: Record<string, string> = {
  delivered: "доставлен",
  timeout: "не успел",
  off_target: "не в точке",
  not_picked_up: "без забора",
  not_finished: "не завершён",
  not_started: "не начат",
};

function noteCodes(n: string | null | undefined): string[] {
  if (!n) return [];
  n = n.split("|")[0].trim();
  if (!n) return [];
  return CODE_RU[n] ? [n] : n.split(/\s+/);
}
const codeRu = (c: string): string =>
  CODE_RU[c] || (c.indexOf("zone:") === 0 ? "зона скорости " + c.slice(5) + " м/с" : c);
/** Подпись поля `nt` контроллера (что он сейчас делает). */
export const noteRu = (n: string | null | undefined): string => noteCodes(n).map(codeRu).join(", ");
