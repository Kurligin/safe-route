/* Рабочее место оператора «Безопасный маршрут».
   Данные: /data.js (сводки прогонов, сценарии, карта), тики прогона — /api/run/<id>,
   запуск — POST /api/launch и опрос /api/jobs, свои сценарии — POST /api/scenario. */
(function () {
  "use strict";
  const RUNS = window.RUNS || {};
  const SCENS = window.SCENS || {};
  const SCEN_LIST = window.SCEN_LIST || [];
  const CTRLS = window.CTRLS || [];
  const BASEMAP = window.BASEMAP || { bounds: [0, 0, 250, 200], drivable: [], buildings: [], points: {}, zones: [] };
  const ARM = window.ARM || { canRun: false, reason: "сервер не ответил", parallel: 2, avgS: 6 };

  /* ---------- подписи ---------- */
  const esc = (s) =>
    String(s == null ? "" : s).replace(
      /[&<>"']/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
    );
  const SCEN_RU = {
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
  const numOf = (id) => (id.match(/_(\d{2,})(?:_|$)/) || [])[1] || id.split("_").pop();
  const scenInfo = (id) => SCEN_LIST.find((s) => s.id === id);
  const scenRu = (id) => {
    if (SCEN_RU[id]) return SCEN_RU[id];
    const s = scenInfo(id);
    if (s && s.title) return esc(s.title);
    if (id.indexOf("gen_") === 0) return "Скрытоподобный №" + numOf(id);
    if (id.indexOf("stress_pallet") === 0) return "Поддон у оси №" + numOf(id);
    if (id.indexOf("stress_swarm") === 0) return "Толпа невнимательных №" + numOf(id);
    if (id.indexOf("stress_fog") === 0) return "Туман на северной дороге №" + numOf(id);
    if (id.indexOf("stress_") === 0) return "Стресс №" + numOf(id);
    return esc(id);
  };
  // название прогона в списках: демо потери ориентации (прогон inject_*) — отдельной подписью
  const runTitle = (k) => (k.indexOf("inject_") === 0 ? "Потеря ориентации (демо)" : scenRu(RUNS[k].scenario));
  const PT_RU = { warehouse: "Склад", shop_a: "Цех A", shop_b: "Цех B", charger: "Зарядка" };
  const ptRu = (p) => PT_RU[p] || esc(p);
  const BUILD_RU = { W: "Склад", A: "Цех A", B: "Цех B", T: "Высокий корпус T", S: "Корпус S", N1: "Корпус N1" };
  const buildRu = (id) =>
    BUILD_RU[id] ||
    { K1: "Киоск", FENCE_W: "Забор" }[id] ||
    (/^CAN_\d+$/.test(id) ? "Опора навеса " + id.slice(4) : /_bay_/.test(id) ? "Стенка дока " + id : esc(id));
  const TIP = {
    "Наш контроллер":
      "Позиция считается по колёсам и гироскопу и уточняется лидаром по карте стен и спутником (фильтр Калмана). Так же работает реальная машина.",
    Baseline:
      "Пример контроллера от организаторов: колёса + спутник, без привязки к карте по лидару. Теряется в тени ГНСС.",
  };
  const SCORE_TIP =
    "Счёт симулятора за один прогон, 0–100. Доставка — до 40 (доля доставленных рейсов), эффективность — до 15 (быстрота относительно эталона), безопасность — до 25 (дистанция до людей), правила — до 10 (дороги, запретные и скоростные зоны), честность позы — до 10 (ошибка оценки позиции меньше 1 м, статусы совпадают с движением). Каждый удар −30. Наезд на человека в движении или ни одной доставки — 0 за сценарий.";
  const GROUPS = ["Открытые", "Учебные", "Скрытоподобные", "Стресс", "Проверочные", "Витрина", "Свои"];
  const SCEN_TIP = {
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
  const CODE_RU = {
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
  const EP_RU = {
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
  const ST_RU = {
    moving: "едет",
    arrived: "прибыл",
    waiting: "ждёт",
    lost: "потерял позицию",
    estop: "аварийный стоп",
  };
  const REASON_RU = {
    delivered: "доставлен",
    timeout: "не успел",
    off_target: "не в точке",
    not_picked_up: "без забора",
    not_finished: "не завершён",
    not_started: "не начат",
  };
  const SOFT = /^(zone:|dock$|pickup$)/; // поясняют движение, но сами не причина остановки
  function noteCodes(n) {
    if (!n) return [];
    n = n.split("|")[0].trim();
    if (!n) return [];
    return CODE_RU[n] ? [n] : n.split(/\s+/);
  }
  const codeRu = (c) => CODE_RU[c] || (c.indexOf("zone:") === 0 ? "зона скорости " + c.slice(5) + " м/с" : c);
  const noteRu = (n) => esc(noteCodes(n).map(codeRu).join(", "));
  const causeRu = (n) =>
    esc(
      noteCodes(n)
        .filter((c) => !SOFT.test(c))
        .map(codeRu)
        .join(", "),
    );

  const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const C = {
    accent: css("--accent"), cmp: css("--cmp"), ok: css("--ok"), warn: css("--warn"), bad: css("--bad"),
    fg: css("--fg"), fg2: css("--fg-2"), fg3: css("--fg-3"), line: css("--line"), view: css("--view"),
  }; // prettier-ignore
  const $ = (s, r = document) => r.querySelector(s);
  const el = (tag, cls, html) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  };
  const fmtT = (t) => {
    t = Math.max(0, t);
    const m = Math.floor(t / 60),
      s = t - m * 60;
    return m + ":" + (s < 10 ? "0" : "") + s.toFixed(1);
  };
  const f2 = (v) => (v == null ? "—" : v.toFixed(2));
  const plural = (n, a, b, c) =>
    n % 10 === 1 && n % 100 !== 11 ? a : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20) ? b : c;
  const scoreCls = (v) => (v < 50 ? "bad" : v < 90 ? "warn" : "ok");

  /* ---------- сервер ---------- */
  async function api(path, body) {
    const r = await fetch(
      path,
      body === undefined
        ? {}
        : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) },
    );
    const d = await r.json().catch(() => ({ error: "сервер вернул не JSON" }));
    if (!r.ok || d.error) throw new Error(d.error || "ошибка " + r.status);
    return d;
  }

  /* ---------- прогоны: порядок, пары, загрузка тиков ---------- */
  const CTRL_ORDER = { ours: 0, baseline: 1 };
  const gIdx = (id) => {
    const s = scenInfo(id);
    return s ? GROUPS.indexOf(s.group) : 99;
  };
  let RUN_ORDER = [];
  function refreshOrder() {
    RUN_ORDER = Object.keys(RUNS).sort((a, b) => {
      const A = RUNS[a],
        B = RUNS[b];
      return (
        gIdx(A.scenario) - gIdx(B.scenario) ||
        A.scenario.localeCompare(B.scenario) ||
        (CTRL_ORDER[A.ctrl] ?? 9) - (CTRL_ORDER[B.ctrl] ?? 9) ||
        A.seed - B.seed ||
        a.localeCompare(b)
      );
    });
  }
  const sameScen = (k) => RUN_ORDER.filter((x) => x !== k && RUNS[x].scenario === RUNS[k].scenario);
  /** Пара для сравнения: другой контроллер на том же seed, затем другой контроллер, затем другой seed. */
  function pairFor(k) {
    if (!k || !RUNS[k]) return null;
    const R = RUNS[k],
      c = sameScen(k);
    const rank = (x) => (RUNS[x].ctrl !== R.ctrl ? 0 : 2) + (RUNS[x].seed === R.seed ? 0 : 1);
    c.sort((a, b) => rank(a) - rank(b));
    return c[0] || null;
  }
  function prepRefs(key) {
    const R = RUNS[key],
      T = R.ticks,
      refs = {};
    const sc = SCENS[R.scenario];
    if (sc) sc.missions.forEach((m) => (refs[m.id] = m.ref));
    for (let i = 0; i < T.t.length; i += 5) {
      const m = T.m[i];
      if (!m || (sc && refs[m])) continue;
      (refs[m] = refs[m] || []).push([T.x[i], T.y[i]]);
    }
    R._refs = refs;
  }
  const loading = {};
  function ensureFull(key) {
    if (!key || !RUNS[key] || RUNS[key].ticks) return Promise.resolve();
    if (!loading[key]) {
      loading[key] = api("/api/run/" + encodeURIComponent(key))
        .then((d) => {
          Object.assign(RUNS[key], d);
          RUNS[key]._d = null;
          prepRefs(key);
        })
        .finally(() => delete loading[key]);
    }
    return loading[key];
  }

  /* ---------- производные данные прогона ---------- */
  function inside(x, y, poly) {
    let c = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const [x1, y1] = poly[i],
        [x2, y2] = poly[j];
      if (y1 > y !== y2 > y && x < x1 + ((y - y1) * (x2 - x1)) / (y2 - y1)) c = !c;
    }
    return c;
  }
  function bandsWhere(T, pred) {
    const out = [];
    let s = null;
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
  function derive(key) {
    const R = RUNS[key];
    if (R._d) return R._d;
    const T = R.ticks,
      n = T.t.length;
    const shadows = ((R.map || BASEMAP).zones || []).filter((z) => z.type === "gnss_shadow").map((z) => z.polygon);
    const d = {};
    d.tEnd = n ? T.t[n - 1] : 0;
    d.shadow = bandsWhere(T, (i) => shadows.some((p) => inside(T.x[i], T.y[i], p)));
    d.fog = R.events.filter((e) => e.type === "fog_bank").map((e) => [e.t1, e.t2]);
    d.outage = R.events.filter((e) => e.type === "gnss_outage").map((e) => [e.t1, e.t2]);
    d.drops = R.events.filter((e) => e.type === "object_dropped");
    // остановки и замедления: v < 0.05 или причина из note контроллера дольше 1 с
    const stops = [];
    let s = null,
      why = {};
    for (let i = 0; i <= n; i++) {
      const cause = i < n ? causeRu(T.nt[i]) : "";
      const still = i < n && Math.abs(T.v[i]) < 0.05 && Math.abs(T.w[i] || 0) < 0.05; // разворот на месте — не стоп
      const slow = i < n && (still || cause.length > 0) && T.st[i] !== "arrived";
      if (slow) {
        if (s == null) {
          s = i;
          why = {};
        }
        const w =
          cause ||
          (T.st[i] === "lost" || T.st[i] === "estop" ? ST_RU[T.st[i]] : "") ||
          (still ? noteRu(T.nt[i]) : "") ||
          (still ? "стоп" : "");
        if (w) why[w] = (why[w] || 0) + 1;
      } else if (s != null) {
        const t0 = T.t[s],
          t1 = T.t[i - 1];
        if (t1 - t0 >= 1.0) {
          const top = Object.keys(why).sort((a, b) => why[b] - why[a])[0] || "стоп";
          let minv = 9;
          for (let k = s; k < i; k++) minv = Math.min(minv, Math.abs(T.v[k]));
          stops.push({ t0, t1, reason: top, full: minv < 0.05, x: T.x[s], y: T.y[s] });
        }
        s = null;
      }
    }
    d.stops = stops;
    d.episodes = (R.score.episodes || []).map((e) => ({ ...e }));
    d.trips = R.missions.map((m) => ({ ...m }));
    d.mBands = R.missions.map((m) => ({ id: m.id, t0: m.t_start, t1: m.t_end, ok: m.delivered }));
    R._d = d;
    return d;
  }
  function idxAt(R, t) {
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

  /* ---------- состояние ---------- */
  const storedLimits = () => {
    try {
      return localStorage.getItem("arm.showLimits") === "1";
    } catch (e) {
      return false;
    }
  };
  const S = { showLimits: storedLimits(), primary: null, compare: null, t: 0, playing: false, speed: 4, follow: false, tab: "run",
    layers: { zones: true, trail: true, est: true, peds: true, path: true, patches: true } }; // prettier-ignore
  const listeners = [];
  const onChange = (fn) => listeners.push(fn);
  const emit = () => listeners.forEach((f) => f());
  const ready = (k) => !!(k && RUNS[k] && RUNS[k].ticks);
  const tMax = () =>
    Math.max(ready(S.primary) ? derive(S.primary).tEnd : 0, ready(S.compare) ? derive(S.compare).tEnd : 0) || 1;
  function seek(t, pause) {
    S.t = Math.max(0, Math.min(tMax(), t));
    if (pause) S.playing = false;
    emit();
  }

  /* ---------- карта ---------- */
  function MapView(host, getKeys, opts) {
    opts = opts || {};
    const cv = el("canvas");
    host.appendChild(cv);
    const ctx = cv.getContext("2d");
    let W = 0,
      H = 0,
      dpr = 1,
      sc = 4,
      ox = 0,
      oy = 0,
      fitted = false;
    function fit() {
      const r = host.getBoundingClientRect();
      W = r.width;
      H = r.height;
      dpr = window.devicePixelRatio || 1;
      cv.width = W * dpr;
      cv.height = H * dpr;
      if (!fitted && W > 0) {
        const bx0 = 8,
          by0 = 66,
          bx1 = 250,
          by1 = 194;
        sc = Math.min((W - 40) / (bx1 - bx0), (H - 40) / (by1 - by0));
        ox = W / 2 - ((bx0 + bx1) / 2) * sc;
        oy = H / 2 + ((by0 + by1) / 2) * sc;
        fitted = true;
      }
      draw();
    }
    const X = (x) => ox + x * sc,
      Y = (y) => oy - y * sc;
    function poly(p, fill, stroke, lw, dash) {
      ctx.beginPath();
      p.forEach(([x, y], i) => (i ? ctx.lineTo(X(x), Y(y)) : ctx.moveTo(X(x), Y(y))));
      ctx.closePath();
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
    function hatch(p, color) {
      ctx.save();
      ctx.beginPath();
      p.forEach(([x, y], i) => (i ? ctx.lineTo(X(x), Y(y)) : ctx.moveTo(X(x), Y(y))));
      ctx.closePath();
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
    function robot(x, y, th, color, fillA, dashed) {
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
    function trail(R, i, key, color, dash, lw) {
      const T = R.ticks;
      ctx.beginPath();
      let started = false;
      for (let k = 0; k <= i; k += 2) {
        const x = T[key[0]][k],
          y = T[key[1]][k];
        if (x == null) {
          started = false;
          continue;
        }
        if (!started) {
          ctx.moveTo(X(x), Y(y));
          started = true;
        } else ctx.lineTo(X(x), Y(y));
      }
      ctx.strokeStyle = color;
      ctx.lineWidth = lw || 1.5;
      ctx.setLineDash(dash || []);
      ctx.stroke();
      ctx.setLineDash([]);
    }
    function draw() {
      if (!W) return;
      const keys = opts.editor ? [] : getKeys().filter(ready);
      const R = keys.length ? RUNS[keys[0]] : null;
      const M = opts.getMap ? opts.getMap() : (R && R.map) || BASEMAP,
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
      if (L.zones || opts.editor) {
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
          if (p.op === "add") {
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
      const small = sc >= 5;
      ctx.font = "500 10px Inter, sans-serif";
      ctx.fillStyle = "rgba(232,234,237,0.45)";
      ctx.textAlign = "left";
      if (small) {
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
        const ru =
          { warehouse: "Док склада", shop_a: "Док цеха A", shop_b: "Док цеха B", charger: "Зарядка" }[name] || name;
        ctx.textAlign = "center";
        ctx.fillText(ru, X(p.x) - (name === "shop_b" ? 22 : 0), Y(p.y) + 14);
        ctx.textAlign = "left";
      });
      keys.forEach((key, ki) => {
        const Rk = RUNS[key],
          i = idxAt(Rk, S.t),
          T = Rk.ticks;
        const cm = !!S.compare && key === S.compare;
        const col = cm ? C.cmp : C.accent;
        // путь текущего рейса
        if (L.path && ki === 0) {
          const mid = T.m[i];
          const ref = mid && Rk._refs ? Rk._refs[mid] : null;
          if (ref && ref.length) {
            ctx.beginPath();
            ref.forEach(([x, y], k) => (k ? ctx.lineTo(X(x), Y(y)) : ctx.moveTo(X(x), Y(y))));
            ctx.strokeStyle = "rgba(232,234,237,0.18)";
            ctx.lineWidth = 3;
            ctx.stroke();
          }
        }
        if (L.trail) trail(Rk, i, ["x", "y"], cm ? "rgba(232,119,46,0.75)" : "rgba(74,140,255,0.75)", null, 1.6);
        if (L.est) trail(Rk, i, ["px", "py"], cm ? "rgba(232,119,46,0.9)" : "rgba(232,234,237,0.55)", [4, 4], 1.2);
        // упавший предмет
        Rk.events
          .filter((e) => e.type === "object_dropped" && S.t >= e.t)
          .forEach((e) => {
            ctx.beginPath();
            ctx.arc(X(e.x), Y(e.y), Math.max(3, e.r * sc), 0, Math.PI * 2);
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
        if (L.est && T.px[i] != null)
          robot(T.px[i], T.py[i], T.pth[i], cm ? C.cmp : "rgba(232,234,237,0.8)", null, true);
        robot(T.x[i], T.y[i], T.th[i], col, cm ? "rgba(232,119,46,0.25)" : "rgba(74,140,255,0.28)");
      });
      if (opts.overlay) opts.overlay(ctx, X, Y, sc);
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
    // взаимодействие
    let drag = null;
    cv.addEventListener("mousedown", (e) => {
      drag = [e.clientX, e.clientY, ox, oy];
      S.follow = false;
    });
    window.addEventListener("mouseup", (e) => {
      if (drag && opts.onClick && Math.hypot(e.clientX - drag[0], e.clientY - drag[1]) < 4) {
        const r = cv.getBoundingClientRect();
        opts.onClick((e.clientX - r.left - ox) / sc, (oy - (e.clientY - r.top)) / sc);
      }
      drag = null;
    });
    window.addEventListener("mousemove", (e) => {
      if (!drag) return;
      ox = drag[2] + e.clientX - drag[0];
      oy = drag[3] + e.clientY - drag[1];
      draw();
    });
    cv.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        const r = cv.getBoundingClientRect();
        const mx = e.clientX - r.left,
          my = e.clientY - r.top;
        const k = Math.exp(-e.deltaY * 0.0015);
        const wx = (mx - ox) / sc,
          wy = (oy - my) / sc;
        sc *= k;
        ox = mx - wx * sc;
        oy = my + wy * sc;
        draw();
      },
      { passive: false },
    );
    const firstReady = () => getKeys().filter(ready)[0];
    const view = {
      draw() {
        const k = firstReady();
        if (S.follow && k) {
          const R = RUNS[k],
            i = idxAt(R, S.t);
          ox = W / 2 - R.ticks.x[i] * sc;
          oy = H / 2 + R.ticks.y[i] * sc;
        }
        draw();
      },
      fit,
      zoom(k) {
        const cx = W / 2,
          cy = H / 2,
          wx = (cx - ox) / sc,
          wy = (oy - cy) / sc;
        sc *= k;
        ox = cx - wx * sc;
        oy = cy + wy * sc;
        draw();
      },
      reset() {
        fitted = false;
        fit();
      },
    };
    const ctl = el("div", "mapctl");
    ctl.innerHTML = `<button title="Приблизить" data-z="in">+</button><button title="Отдалить" data-z="out">−</button><span class="sep"></span>
      <button title="Вся площадка" data-z="fit"><svg viewBox="0 0 16 16"><path d="M2 6V2h4M10 2h4v4M14 10v4h-4M6 14H2v-4" fill="none" stroke="currentColor" stroke-width="1.6"/></svg></button>
      <button title="К тележке" data-z="bot"><svg viewBox="0 0 16 16"><circle cx="8" cy="8" r="3" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M8 1v3M8 12v3M1 8h3M12 8h3" stroke="currentColor" stroke-width="1.6"/></svg></button>`;
    if (opts.editor) ctl.querySelector('[data-z="bot"]').remove();
    host.appendChild(ctl);
    ctl.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      const z = b.dataset.z;
      if (z === "in") view.zoom(1.35);
      if (z === "out") view.zoom(1 / 1.35);
      if (z === "fit") {
        S.follow = false;
        const f = document.getElementById("follow");
        if (f) f.checked = false;
        view.reset();
      }
      const k = firstReady();
      if (z === "bot" && k) {
        const R = RUNS[k],
          i = idxAt(R, S.t);
        sc = Math.max(sc, 9);
        ox = W / 2 - R.ticks.x[i] * sc;
        oy = H / 2 + R.ticks.y[i] * sc;
        draw();
      }
    });
    new ResizeObserver(fit).observe(host);
    return view;
  }

  /* ---------- нижняя панель: шкала и графики ---------- */
  function Tracks(host, getKeys) {
    const cv = el("canvas");
    host.appendChild(cv);
    const ctx = cv.getContext("2d");
    let W = 0,
      H = 0,
      dpr = 1;
    const LX = 118,
      RX = 14;
    const rows = [
      { k: "axis", h: 16 }, { k: "cond", h: 12, lbl: "условия" }, { k: "miss", h: 12, lbl: "рейсы" },
      { k: "stop", h: 12, lbl: "остановки" },
      { k: "v", h: 34, lbl: "скорость, м/с", max: 1.5 },
      { k: "err", h: 34, lbl: "ошибка позы, м", max: 2 },
      { k: "hum", h: 34, lbl: "зазор до чел., м", max: 8 },
    ]; // prettier-ignore
    function fit() {
      const r = host.getBoundingClientRect();
      W = r.width;
      H = r.height;
      dpr = window.devicePixelRatio || 1;
      cv.width = W * dpr;
      cv.height = H * dpr;
      draw();
    }
    const TX = (t) => LX + (t / tMax()) * (W - LX - RX);
    function draw() {
      if (!W) return;
      const keys = getKeys().filter(ready);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, W, H);
      if (!keys.length) return;
      const total = rows.reduce((a, r) => a + r.h + 4, 0);
      const k = (H - 6) / total;
      let y = 4;
      ctx.font = "11px Inter, sans-serif";
      ctx.textBaseline = "middle";
      rows.forEach((row) => {
        const h = row.h * k;
        if (row.lbl) {
          ctx.fillStyle = C.fg2;
          ctx.textAlign = "right";
          ctx.fillText(row.lbl, LX - 10, y + h / 2);
        }
        if (row.k === "axis") {
          const tm = tMax();
          const step = tm > 300 ? 60 : 30;
          ctx.fillStyle = C.fg3;
          ctx.textAlign = "center";
          ctx.font = "10px JetBrains Mono, monospace";
          for (let t = 0; t <= tm; t += step) {
            ctx.fillText(fmtT(t).replace(".0", ""), TX(t), y + h / 2);
            ctx.fillStyle = "rgba(255,255,255,0.04)";
            ctx.fillRect(TX(t), y + h, 1, H);
            ctx.fillStyle = C.fg3;
          }
          ctx.font = "11px Inter, sans-serif";
        } else if (row.k === "cond") {
          ctx.fillStyle = "rgba(255,255,255,0.03)";
          ctx.fillRect(LX, y, W - LX - RX, h);
          const d = derive(keys[0]);
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
            ctx.fillStyle = C.warn;
            ctx.beginPath();
            ctx.moveTo(TX(e.t), y);
            ctx.lineTo(TX(e.t) + 5, y + h);
            ctx.lineTo(TX(e.t) - 5, y + h);
            ctx.fill();
          });
        } else if (row.k === "miss") {
          keys.forEach((key, ki) => {
            derive(key).mBands.forEach((m) => {
              ctx.fillStyle = m.ok ? (ki ? "rgba(232,119,46,0.55)" : "rgba(90,168,111,0.6)") : "rgba(196,89,90,0.7)";
              const yy = keys.length > 1 ? y + (ki * h) / 2 : y,
                hh = keys.length > 1 ? h / 2 - 1 : h;
              ctx.fillRect(TX(m.t0) + 1, yy, TX(m.t1) - TX(m.t0) - 2, hh);
              if (keys.length === 1) {
                ctx.fillStyle = "#0b0d11";
                ctx.textAlign = "left";
                ctx.font = "600 10px Inter";
                ctx.fillText(m.id + (m.ok ? " ✓" : " ✗"), TX(m.t0) + 4, y + h / 2 + 1);
                ctx.font = "11px Inter, sans-serif";
              }
            });
          });
        } else if (row.k === "stop") {
          keys.forEach((key, ki) => {
            const yy = keys.length > 1 ? y + (ki * h) / 2 : y,
              hh = keys.length > 1 ? h / 2 - 1 : h;
            derive(key).stops.forEach((s) => {
              ctx.fillStyle = s.full ? (ki ? C.cmp : C.warn) : ki ? "rgba(232,119,46,0.45)" : "rgba(201,162,39,0.45)";
              ctx.fillRect(TX(s.t0), yy, Math.max(2, TX(s.t1) - TX(s.t0)), hh);
            });
            derive(key).episodes.forEach((e) => {
              ctx.fillStyle = C.bad;
              ctx.beginPath();
              ctx.arc(TX(e.t_start), yy + hh / 2, 3.5, 0, Math.PI * 2);
              ctx.fill();
            });
          });
        } else {
          ctx.fillStyle = "rgba(255,255,255,0.025)";
          ctx.fillRect(LX, y, W - LX - RX, h);
          const Yv = (v) => y + h - (Math.min(row.max, Math.max(0, v)) / row.max) * h;
          const hline = (v, color) => {
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
          keys.forEach((key, ki) => {
            const T = RUNS[key].ticks;
            const n = T.t.length;
            const stepk = Math.max(1, Math.floor(n / (W - LX)));
            if (row.k === "v" && ki === 0) {
              ctx.strokeStyle = "rgba(201,162,39,0.5)";
              ctx.lineWidth = 1;
              ctx.beginPath();
              for (let i = 0; i < n; i += stepk) {
                const vm = T.vmax[i] == null ? 1.39 : T.vmax[i];
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
              const v = row.k === "v" ? Math.abs(T.v[i]) : T[row.k][i];
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
          ctx.fillText(String(row.max), LX + 3, y + 7);
          ctx.font = "11px Inter, sans-serif";
        }
        y += h + 4 * k;
      });
      // курсор
      const cx = TX(S.t);
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
    let down = false;
    const toT = (e) => {
      const r = cv.getBoundingClientRect();
      return ((e.clientX - r.left - LX) / (W - LX - RX)) * tMax();
    };
    cv.addEventListener("mousedown", (e) => {
      down = true;
      seek(toT(e), false);
    });
    window.addEventListener("mousemove", (e) => {
      if (down) seek(toT(e), false);
    });
    window.addEventListener("mouseup", () => (down = false));
    new ResizeObserver(fit).observe(host);
    return { draw };
  }

  /* ---------- панели ---------- */
  const BLK = [["delivery", "Доставка"], ["efficiency", "Эффективность"], ["safety", "Безопасность"], ["rules", "Правила"],
    ["pose", "Честность позы"], ["collisions", "Столкновения"]]; // prettier-ignore
  const blockVal = (s, k) => (s.blocks[k] == null ? 0 : s.blocks[k]);
  function scoreHTML(key, cmpKey) {
    const s = RUNS[key].score,
      c = cmpKey && RUNS[cmpKey] ? RUNS[cmpKey].score : null;
    let h = `<div class="score-big"><span class="n">${s.total.toFixed(2)}</span><span class="of">/ 100</span>${c ? `<span class="cmp">${c.total.toFixed(2)}</span>` : ""}</div><div class="blocks">`;
    BLK.forEach(([k, lbl]) => {
      const mx = s.max[k] || 1,
        v = blockVal(s, k);
      const w = k === "collisions" ? (v < 0 ? 100 : 0) : (Math.max(0, v) / mx) * 100;
      const cv = c ? blockVal(c, k) : 0;
      const wc = c ? (k === "collisions" ? (cv < 0 ? 100 : 0) : (Math.max(0, cv) / mx) * 100) : 0;
      const badv = k === "collisions" ? v < 0 : v < mx - 0.01;
      h += `<div class="blk ${badv ? "bad" : ""}"><span class="lbl">${lbl}</span><span class="bar"><i style="width:${w}%;${k === "collisions" ? "background:var(--bad)" : ""}"></i>${c ? `<i class="c" style="width:${wc}%"></i>` : ""}</span><span class="val">${v.toFixed(1)}</span></div>`;
    });
    return h + "</div>";
  }
  /* прогоны витрины «граница возможностей» скрыты, пока не включён переключатель; выбранные видны всегда */
  const visible = (keys) =>
    S.showLimits ? keys : keys.filter((k) => !RUNS[k].limit || k === S.primary || k === S.compare);
  function limitsToggleHTML() {
    if (!Object.values(RUNS).some((R) => R.limit)) return "";
    return `<label class="toggle ${S.showLimits ? "on" : ""}" style="margin:0 0 6px 2px;font-size:12px"><input type="checkbox" data-limits ${S.showLimits ? "checked" : ""}><span class="sw"></span>Показать сценарии-ограничения</label>`;
  }
  function runListHTML() {
    if (!RUN_ORDER.length) return `<div class="dim">Прогонов пока нет.</div>`;
    return (
      limitsToggleHTML() +
      visible(RUN_ORDER)
        .map((k) => {
          const R = RUNS[k];
          const cls = k === S.primary ? "on" : k === S.compare ? "cmp" : "";
          return `<button class="run ${cls}" data-run="${esc(k)}"><span class="nm">${runTitle(k)}</span><span class="sc ${R.score.total < 50 ? "bad" : ""}">${R.score.total.toFixed(2)}</span><span class="sub">${esc(R.label)} · seed ${R.seed} <span class="tip" tabindex="0" data-tip="${TIP[R.label] || ""}">?</span></span><span class="sub id mono">${esc(k)}</span></button>`;
        })
        .join("")
    );
  }
  function nowHTML(keys) {
    keys = keys.filter(ready);
    if (!keys.length) return `<div class="dim">—</div>`;
    const R = RUNS[keys[0]],
      i = idxAt(R, S.t),
      T = R.ticks;
    const C2 = keys[1] ? RUNS[keys[1]] : null,
      j = C2 ? idxAt(C2, S.t) : 0,
      T2 = C2 ? C2.ticks : null;
    const mid = T.m[i];
    const mh = R.missions_hdr.find((m) => m.id === mid);
    const nt = noteRu(T.nt[i]);
    const err = T.err[i],
      hum = T.hum[i];
    const two = !!T2;
    const st2 = (st) => `<span class="status ${esc(st)}">${ST_RU[st] || esc(st)}</span>`;
    let h = `<div class="rows ${two ? "two" : ""}">`;
    const row = (k, v1, v2, cls1, cls2) =>
      (h += `<div class="r"><span class="k">${k}</span><span class="v ${cls1 || ""}">${v1}</span>${two ? `<span class="v c ${cls2 || ""}">${v2}</span>` : ""}</div>`);
    if (two)
      h += `<div class="r hd"><span class="k"></span><span class="v" style="color:var(--accent)">● ${esc(R.label)}</span><span class="v c">● ${esc(C2.label)}</span></div>`;
    row("Статус", st2(T.st[i]), two ? st2(T2.st[j]) : "");
    const nt2 = two ? noteRu(T2.nt[j]) : "";
    row("Причина", nt || "—", nt2 || "—", nt ? "warn" : "dim", nt2 ? "warn" : "dim");
    h += `<div class="r"><span class="k">Рейс</span><span class="v" style="grid-column:2 / -1">${mh ? `${esc(mh.id)} · ${ptRu(mh.from)} → ${ptRu(mh.to)}` : "—"}</span></div>`;
    row("Скорость", f2(Math.abs(T.v[i])) + " м/с", two ? f2(Math.abs(T2.v[j])) + " м/с" : "");
    const ecls = (e) => (e == null ? "" : e > 1 ? "bad" : e > 0.5 ? "warn" : "");
    row("Ошибка позы", f2(err) + " м", two ? f2(T2.err[j]) + " м" : "", ecls(err), two ? ecls(T2.err[j]) : "");
    const hcls = (x) => (x != null && x < 3 ? "warn" : "");
    row(
      "Зазор до человека",
      hum == null ? "—" : f2(hum) + " м",
      two ? (T2.hum[j] == null ? "—" : f2(T2.hum[j]) + " м") : "",
      hcls(hum),
      two ? hcls(T2.hum[j]) : "",
    );
    return h + "</div>";
  }
  function tripsHTML(key) {
    const d = derive(key);
    let h = `<table class="list"><tr><th>Рейс</th><th>Маршрут</th><th>Время</th><th>Итог</th></tr>`;
    d.trips.forEach((m) => {
      const dur = (m.t_arrival != null ? m.t_arrival : m.t_end) - m.t_start;
      const cur = S.t >= m.t_start && S.t < m.t_end ? "cur" : "";
      const rs = REASON_RU[m.reason] || esc(m.reason);
      h += `<tr class="click ${cur}" data-seek="${m.t_start}"><td class="mono">${esc(m.id)}</td><td>${ptRu(m.from)} → ${ptRu(m.to)}</td><td class="mono">${dur.toFixed(1)} / ${m.deadline_s.toFixed(0)} с</td><td class="${m.delivered ? "ok" : "bad"}">${rs}</td></tr>`;
    });
    return (
      h +
      "</table>" +
      (d.trips.length ? "" : `<div class="dim" style="margin-top:8px;font-size:12px">Рейсов в логе нет.</div>`)
    );
  }
  function eventsHTML(key) {
    const d = derive(key);
    const items = [];
    d.episodes.forEach((e) =>
      items.push({
        t: e.t_start,
        dur: e.t_end - e.t_start,
        kind: "штраф",
        txt: (EP_RU[e.type] || esc(e.type)) + " · " + (e.cost ? e.cost.toFixed(1) : "0") + " б.",
        cls: "bad",
      }),
    );
    d.stops.forEach((s) =>
      items.push({
        t: s.t0,
        dur: s.t1 - s.t0,
        kind: s.full ? "стоп" : "медленно",
        txt: s.reason,
        cls: s.full ? "warn" : "dim",
      }),
    );
    items.sort((a, b) => a.t - b.t);
    let h = `<table class="list"><tr><th>t</th><th>Длит.</th><th>Что</th><th>Причина</th></tr>`;
    items.forEach((it) => {
      const cur = S.t >= it.t && S.t <= it.t + it.dur ? "cur" : "";
      h += `<tr class="click ${cur}" data-seek="${Math.max(0, it.t - 2)}" data-pause="1"><td class="mono">${fmtT(it.t)}</td><td class="mono">${it.dur.toFixed(1)} с</td><td class="${it.cls}">${it.kind}</td><td>${it.txt}</td></tr>`;
    });
    return (
      h +
      "</table>" +
      (d.episodes.length
        ? ""
        : `<div class="dim" style="margin-top:8px;font-size:12px">Штрафных эпизодов в этом прогоне нет.</div>`)
    );
  }

  /* ---------- экспорт CSV (UTF-8 с BOM, «;», десятичная запятая — открывается в Excel) ---------- */
  const cell = (c) =>
    c == null
      ? ""
      : typeof c === "number"
        ? String(+c.toFixed(3)).replace(".", ",")
        : /^[=+\-@\t]/.test(String(c)) // текст, похожий на формулу, Excel выполнит: экранируем апострофом
          ? "'" + String(c).replace(/[;\n\r]/g, ",")
          : String(c).replace(/[;\n\r]/g, ",");
  function downloadCSV(name, rows) {
    const text = "﻿" + rows.map((r) => r.map(cell).join(";")).join("\r\n");
    const a = el("a");
    a.href = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
    a.download = name;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      URL.revokeObjectURL(a.href);
      a.remove();
    }, 1000);
  }
  function exportTrips() {
    if (!ready(S.primary)) return;
    const d = derive(S.primary);
    downloadCSV(`${S.primary}_рейсы.csv`, [["рейс", "откуда", "куда", "начало, с", "прибытие, с", "дедлайн, с", "доставлен", "причина"]].concat(
      d.trips.map((m) => [m.id, PT_RU[m.from] || m.from, PT_RU[m.to] || m.to, m.t_start, m.t_arrival, m.deadline_s, m.delivered ? "да" : "нет", REASON_RU[m.reason] || m.reason]),
    )); // prettier-ignore
  }
  function exportEvents() {
    if (!ready(S.primary)) return;
    const d = derive(S.primary);
    const plain = (s) => el("span", null, s).textContent;
    downloadCSV(`${S.primary}_остановки.csv`, [["начало, с", "конец, с", "тип", "причина", "x", "y"]]
      .concat(d.stops.map((s) => [s.t0, s.t1, s.full ? "стоп" : "медленно", plain(s.reason), s.x, s.y]))
      .concat(d.episodes.map((e) => [e.t_start, e.t_end, "штраф", (EP_RU[e.type] || e.type) + " (" + e.cost + " б.)", e.x, e.y]))); // prettier-ignore
  }

  /* ---------- очередь прогонов на сервере ---------- */
  const JOBS = {}; // id -> задание с сервера
  const handled = new Set(); // завершённые задания, чей прогон уже подгружен
  const hooks = []; // кто хочет знать об изменениях очереди
  let pollTimer = null;
  async function addRun(key) {
    const d = await api("/api/run/" + encodeURIComponent(key) + "?lite=1");
    RUNS[key] = d; // перезапуск с тем же seed заменяет старый прогон
    refreshOrder();
  }
  async function poll() {
    pollTimer = null;
    let list = null;
    try {
      list = await api("/api/jobs");
    } catch (e) {
      list = null;
    }
    const fresh = [];
    if (list) {
      list.forEach((j) => (JOBS[j.id] = j));
      for (const j of list) {
        if (j.state === "done" && !handled.has(j.id)) {
          handled.add(j.id);
          try {
            await addRun(j.key);
            fresh.push(j);
          } catch (e) {
            j.state = "error";
            j.error = e.message;
          }
        } else if (j.state === "error") handled.add(j.id);
      }
    }
    hooks.forEach((f) => f(fresh));
    const active = Object.values(JOBS).some((j) => j.state === "queued" || j.state === "run");
    if (active || !list) pollTimer = setTimeout(poll, list ? 300 : 1500);
  }
  function startPolling() {
    if (!pollTimer) pollTimer = setTimeout(poll, 60);
  }
  async function launchJobs(scenario, controllers, seeds) {
    const r = await api("/api/launch", { scenario, controllers, seeds });
    r.jobs.forEach((id) => {
      if (!JOBS[id]) JOBS[id] = { id, scenario, state: "queued", p: 0 };
      handled.delete(id);
    });
    startPolling();
    return r.jobs;
  }

  /* ---------- экран «Запуск» ---------- */
  const scenIds = () => SCEN_LIST.map((s) => s.id);
  const LS = {
    scen: new Set(["02_gnss_shadow", "04_busy_yard"].filter((id) => scenInfo(id))),
    ctrl: new Set(CTRLS.map((c) => c.key)),
    seeds: "1, 2, 3",
    jobs: [],
    running: false,
    error: "",
  };
  const parseSeeds = (t) => [
    ...new Set(
      t
        .split(/[ ,;]+/)
        .map((x) => parseInt(x, 10))
        .filter((x) => x >= 0),
    ),
  ];
  const nJobs = () => LS.scen.size * LS.ctrl.size * parseSeeds(LS.seeds).length;
  const goLabel = () => {
    const n = nJobs();
    return LS.running ? "Выполняется…" : `▶ Запустить ${n} ${plural(n, "прогон", "прогона", "прогонов")}`;
  };
  function launchFullHTML() {
    const groups = GROUPS.map((g) => [g, SCEN_LIST.filter((s) => s.group === g).map((s) => s.id)]).filter(
      ([, ids]) => ids.length,
    );
    const scenChips = groups.map(([g, ids]) => `<div class="grp"><span class="gl">${g} <span class="tip" tabindex="0" data-tip="${SCEN_TIP[g] || ""}">?</span></span><div class="chips">${ids.map((id) => `<button class="chip ${LS.scen.has(id) ? "on" : ""}" data-scen="${esc(id)}">${scenRu(id)}</button>`).join("")}</div></div>`).join(""); // prettier-ignore
    const ctrlChips = CTRLS.map((c) => `<button class="chip ${LS.ctrl.has(c.key) ? "on" : ""}" data-ctrl="${c.key}"><span>${esc(c.label)}</span><span class="tip" tabindex="0" data-tip="${TIP[c.label] || ""}">?</span></button>`).join(""); // prettier-ignore
    const n = nJobs(),
      ns = parseSeeds(LS.seeds).length;
    const mins = Math.max(1, Math.round((n * (ARM.avgS || 6)) / (ARM.parallel || 2) / 60));
    const note = !ARM.canRun
      ? `<div class="lock" style="margin-top:10px">${esc(ARM.reason || "Запуск прогонов недоступен")}</div>`
      : LS.error
        ? `<div class="lock" style="margin-top:10px">${esc(LS.error)}</div>`
        : "";
    return `<div class="launch"><div class="form"><h2>Запуск прогонов</h2>
      <div class="field"><span>Сценарии</span>${scenChips}</div>
      <div class="field"><span>Контроллеры</span><div class="chips">${ctrlChips}</div></div>
      <div class="field"><span>Seed <span class="tip" tabindex="0" data-tip="Seed задаёт случайный шум датчиков и поведение людей. Тот же сценарий с другим seed — те же маршруты, но другие помехи. Жюри гоняет на своих seed, поэтому устойчивость на разных seed важна.">?</span></span><input class="sel mono" id="lSeeds" value="${esc(LS.seeds)}"></div>
      <div class="summary">${LS.scen.size} ${plural(LS.scen.size, "сценарий", "сценария", "сценариев")} × ${LS.ctrl.size} ${plural(LS.ctrl.size, "контроллер", "контроллера", "контроллеров")} × ${ns} seed = <b>${n} ${plural(n, "прогон", "прогона", "прогонов")}</b> · около ${mins} мин</div>
      <button class="btn primary go" id="lGo" ${n && !LS.running && ARM.canRun ? "" : "disabled"}>${goLabel()}</button>${note}
      <div class="field" style="margin-top:14px"><span>Команда для каждого прогона</span><div class="cmdline">python -m amrsim run scenarios/&lt;сценарий&gt;.json --controller &lt;контроллер&gt;/controller.py --seed &lt;seed&gt; --report arm/runs/&lt;id&gt;.json --log arm/runs/&lt;id&gt;.jsonl</div></div>
      </div><div class="out">
      <div class="qhead"><h3>Очередь</h3><span id="qStat" class="dim"></span></div>
      <div class="progress big"><i id="qBar"></i></div>
      <div id="queue">${queueHTML()}</div>
      <h3 style="margin-top:22px">История прогонов</h3>${limitsToggleHTML()}
      <div id="hist">${historyHTML()}</div></div></div>`;
  }
  function queueHTML() {
    const jobs = LS.jobs.map((id) => JOBS[id]).filter(Boolean);
    if (!jobs.length)
      return `<div class="empty">Выберите сценарии, контроллеры и seed слева и нажмите «Запустить». Прогоны пойдут по ${ARM.parallel || 2} одновременно, у каждого своя строка с ходом выполнения.</div>`;
    return (
      `<table class="list q"><tr><th>Сценарий</th><th>Контроллер</th><th>Seed</th><th style="width:34%">Ход</th><th>Итог</th></tr>` +
      jobs
        .map((j) => {
          const st = j.state === "queued" ? `<span class="dim">в очереди</span>` : j.state === "run" ? `<span class="warn">идёт…</span>`
          : j.state === "error" ? `<span class="bad">ошибка</span> <span class="tip" tabindex="0" data-tip="${esc(j.error || "")}">?</span>`
          : `<span class="mono ${scoreCls(j.total)}">${(j.total || 0).toFixed(2)}</span>`; // prettier-ignore
          const open =
            j.state === "done" && RUNS[j.key]
              ? ` <button class="btn small" data-open="${esc(j.key)}">Открыть</button>`
              : "";
          return `<tr><td>${scenRu(j.scenario)}<div class="sub id mono">${esc(j.scenario)}</div></td><td>${esc(j.label || "")}</td><td class="mono">${j.seed}</td><td><div class="progress row ${j.state === "run" ? "live" : ""}"><i style="width:${j.p || 0}%;${j.state === "error" ? "background:var(--bad)" : ""}"></i></div></td><td style="white-space:nowrap">${st}${open}</td></tr>`;
        })
        .join("") +
      "</table>"
    );
  }
  function historyHTML() {
    const keys = visible(Object.keys(RUNS)).sort(
      (a, b) => (RUNS[b].mtime || 0) - (RUNS[a].mtime || 0) || a.localeCompare(b),
    );
    if (!keys.length) return `<div class="empty">Прогонов пока нет.</div>`;
    return (
      `<table class="list"><tr><th>Сценарий</th><th>Контроллер</th><th>Seed</th><th>Итог <span class="tip" tabindex="0" data-tip="${SCORE_TIP}">?</span></th><th>Доставлено</th><th>Шаг, мс</th><th></th></tr>` +
      keys
        .map((k) => {
          const R = RUNS[k];
          return `<tr><td>${runTitle(k)}<div class="sub id mono">${esc(k)}</div></td><td>${esc(R.label)}</td><td class="mono">${R.seed}</td><td class="mono ${scoreCls(R.score.total)}">${R.score.total.toFixed(2)}</td><td class="mono">${R.score.deliveries}/${R.missions.length}</td><td class="mono">${(R.step_ms.mean || 0).toFixed(2)}</td><td style="white-space:nowrap"><button class="btn small" data-open="${esc(k)}">Открыть</button> <button class="btn small" data-cmpopen="${esc(k)}">Сравнить</button></td></tr>`;
        })
        .join("") +
      "</table>"
    );
  }
  async function startBatch() {
    const seeds = parseSeeds(LS.seeds);
    const scen = scenIds().filter((id) => LS.scen.has(id));
    const ctrls = CTRLS.map((c) => c.key).filter((k) => LS.ctrl.has(k));
    LS.jobs = [];
    LS.running = true;
    LS.error = "";
    try {
      for (const sc of scen) LS.jobs.push(...(await launchJobs(sc, ctrls, seeds)));
    } catch (e) {
      LS.error = "Запуск не принят: " + e.message;
      LS.running = LS.jobs.length > 0;
    }
  }

  /* ---------- легенда карты: сворачиваемая плашка в левом нижнем углу ---------- */
  const LG_ITEMS = {
    bot: "тележка (истина)",
    cmpbot: "второй прогон (сравнение)",
    est: "оценка позы",
    trail: "след (истина)",
    esttrail: "след оценки",
    path: "маршрут рейса",
    route: "маршрут рейса",
    ped: "пешеход",
    near: "ближе 3 м к тележке",
    inatt: "невнимательный пешеход",
    pallet: "поддон",
    box: "препятствие не на карте",
    removed: "снесённое здание",
    dock: "док / точка",
    shadow: "тень ГНСС",
    speed: "ограничение скорости",
    people: "место людей",
    forbidden: "запретная зона",
  };
  const LG_SETS = {
    run: [
      [
        "Объекты",
        ["bot", "cmpbot", "est", "trail", "esttrail", "path", "ped", "near", "pallet", "box", "removed", "dock"],
      ],
    ],
    build: [["Объекты", ["route", "ped", "inatt", "pallet", "box", "removed", "dock"]]],
  };
  const LG_ZONES = ["Зоны", ["shadow", "speed", "people", "forbidden"]];
  function legendHTML(kind, id, openByDefault) {
    let open = openByDefault;
    try {
      const v = localStorage.getItem("arm.legend2." + id);
      if (v !== null) open = v === "1";
    } catch (e) {
      /* без localStorage — состояние по умолчанию */
    }
    const groups = LG_SETS[kind].concat([LG_ZONES]);
    const body = groups
      .map(
        ([g, keys]) =>
          `<div class="lg-g">${g}</div>` +
          keys.map((k) => `<span class="lg"><i class="sw sw-${k}"></i>${LG_ITEMS[k]}</span>`).join(""),
      )
      .join("");
    return `<div class="mlegend ${open ? "open" : ""}" data-legend="${id}"><button class="mlegend-h" type="button" aria-expanded="${open}"><span>Легенда</span><svg viewBox="0 0 10 6"><path d="M1 5l4-4 4 4" fill="none" stroke="currentColor" stroke-width="1.5"/></svg></button><div class="mlegend-b">${body}</div></div>`;
  }
  document.addEventListener("click", (e) => {
    const h = e.target.closest(".mlegend-h");
    if (!h) return;
    const box = h.parentElement,
      open = !box.classList.contains("open");
    box.classList.toggle("open", open);
    h.setAttribute("aria-expanded", String(open));
    try {
      localStorage.setItem("arm.legend2." + box.dataset.legend, open ? "1" : "0");
    } catch (err) {
      /* ничего */
    }
  });

  /* ---------- сборка страницы ---------- */
  function build() {
    refreshOrder();
    const app = $("#app");
    const top = el("header", "topbar");
    top.innerHTML =
      `<div class="brand"><span class="dot"></span>SafeRoute <small>· АРМ оператора межцеховой логистики</small></div>` +
      `<nav class="tabs"><button class="tab on" data-tab="run">Прогоны</button><button class="tab" data-tab="launch">Запуск</button><button class="tab" data-tab="build">Конструктор</button></nav>` +
      `<span class="spacer"></span>` +
      `<div class="seg" id="modeSeg"><button class="on" data-mode="run">Один прогон</button><button data-mode="cmp">Сравнение</button></div>` +
      `<button class="btn" id="expTrips">CSV рейсов</button><button class="btn" id="expEv">CSV остановок</button>`;
    app.appendChild(top);

    const main = el("div", "main");
    app.appendChild(main);
    const left = el("aside", "panel");
    main.appendChild(left);
    const left2 = el("aside", "panel");
    left2.hidden = true;
    main.appendChild(left2);
    const view = el("section", "view");
    view.id = "v1";
    main.appendChild(view);
    const view2 = el("section", "view");
    view2.hidden = true;
    main.appendChild(view2);
    const right = el("aside", "panel right");
    main.appendChild(right);
    const launchHost = el("div");
    launchHost.style.cssText = "grid-row:2 / span 2;min-height:0";
    launchHost.hidden = true;
    app.appendChild(launchHost);
    const buildHost = el("div", "builder");
    buildHost.style.cssText = "grid-row:2 / span 2;min-height:0";
    buildHost.hidden = true;
    app.appendChild(buildHost);
    const bottom = el("section", "bottom");
    app.appendChild(bottom);
    bottom.innerHTML = `<div class="player"><button class="play" id="play" aria-label="Пуск">▶</button><span class="time" id="time"></span>
      <div class="speeds">${[1, 4, 16, 32].map((s) => `<button data-sp="${s}" class="${s === S.speed ? "on" : ""}">×${s}</button>`).join("")}</div>
      <label class="toggle" style="margin-left:8px"><input type="checkbox" id="follow"><span class="sw"></span>Следовать за тележкой</label>
      <span class="hint">Пробел — пуск/пауза · ←/→ — ±1 с · Shift — ±10 с · клик по шкале — перемотка</span></div><div class="tracks" id="tracks"></div>`;

    view.innerHTML = `<div class="cap" id="cap1"></div><div class="layers" id="layers">
      ${[
        ["zones", "Зоны"],
        ["path", "Маршрут рейса"],
        ["trail", "След (истина)"],
        ["est", "Оценка позы"],
        ["peds", "Пешеходы"],
        ["patches", "Расхождения карты"],
      ]
        .map(([k, l]) => `<label><input type="checkbox" data-layer="${k}" checked>${l}</label>`)
        .join("")}</div>
      ${legendHTML("run", "main", false)}`;
    view2.innerHTML = `<div class="cap" id="cap2"></div>${legendHTML("run", "cmp", false)}`;

    const keysMain = () =>
      (S.tab === "cmp" ? [S.primary] : S.compare ? [S.primary, S.compare] : [S.primary]).filter(Boolean);
    const map1 = MapView(view, keysMain);
    const map2 = MapView(view2, () => (S.compare ? [S.compare] : []));
    const tracksKeys = () => (S.compare ? [S.primary, S.compare] : [S.primary]).filter(Boolean);
    const tracks = Tracks($("#tracks"), tracksKeys);
    let lastMode = "run";

    /** Выбрать прогон (и пару в режиме сравнения), подгрузить тики и перерисовать. */
    async function openRun(key, mode) {
      if (key && RUNS[key]) S.primary = key;
      if (mode) S.tab = mode;
      if (S.tab === "cmp" && S.primary) {
        const c = S.compare;
        if (!c || c === S.primary || !RUNS[c] || RUNS[c].scenario !== RUNS[S.primary].scenario)
          S.compare = pairFor(S.primary);
      }
      try {
        await Promise.all([ensureFull(S.primary), S.tab === "cmp" ? ensureFull(S.compare) : null]);
      } catch (e) {
        left.insertAdjacentHTML(
          "afterbegin",
          `<div class="lock" style="margin:10px">Не удалось загрузить прогон: ${esc(e.message)}</div>`,
        );
        return;
      }
      S.t = Math.min(S.t, tMax());
      renderPanels();
      emit();
    }

    function renderPanels() {
      const R = S.primary ? RUNS[S.primary] : null;
      if (!ready(S.primary)) {
        left.innerHTML = `<div class="sec"><h3>Прогон</h3><div class="empty">${R ? "Загрузка прогона…" : "Прогонов пока нет. Запустите сценарий во вкладке «Запуск» — результат появится здесь."}</div>${R ? "" : `<button class="btn primary" id="toLaunch" style="width:100%;margin-top:10px">Перейти к запуску</button>`}</div>`;
        const tl = left.querySelector("#toLaunch");
        if (tl) tl.addEventListener("click", () => setTab("launch"));
        right.innerHTML = "";
        left2.innerHTML = "";
        $("#cap1").innerHTML = "";
        $("#cap2").innerHTML = "";
        return;
      }
      const cmp = ready(S.compare) ? S.compare : null;
      if (S.tab === "cmp") {
        const card = (k, col, extra) => {
          const Rr = RUNS[k];
          return `<div class="sec colhead" style="--c:${col}"><h3><span style="color:${col}">● ${esc(Rr.label)} <span class="tip" tabindex="0" data-tip="${TIP[Rr.label] || ""}">?</span></span></h3><div class="kv"><dt>Сценарий</dt><dd>${runTitle(k)}</dd><dt>Seed</dt><dd class="mono">${Rr.seed}</dd><dt>Длительность</dt><dd class="mono">${fmtT(derive(k).tEnd)}</dd><dt>Шаг</dt><dd class="mono">${(Rr.step_ms.mean || 0).toFixed(2)} мс</dd></div></div>
          <div class="sec"><h3><span>Счёт сценария <span class="tip" tabindex="0" data-tip="${SCORE_TIP}">?</span></span></h3>${scoreHTML(k)}</div>${extra || ""}`;
        };
        left.innerHTML = card(
          S.primary,
          "var(--accent)",
          `<div class="sec"><h3>Пара прогонов</h3><div class="run-list">${runListHTML()}</div></div>`,
        );
        const others = visible(sameScen(S.primary));
        const short = (k) => RUNS[k].label + " · seed " + RUNS[k].seed;
        const optLabel = (k) =>
          esc(others.some((o) => o !== k && short(o) === short(k)) ? short(k) + " · " + k : short(k));
        const other = CTRLS.find((c) => c.key !== R.ctrl) || CTRLS[0];
        const pairLaunch = `<div class="reseed" style="grid-template-columns:1fr auto"><span class="dim">${esc(other ? other.label : "")} · seed ${R.seed}</span><button class="btn small" id="pairGo" ${ARM.canRun && other ? "" : "disabled"}>Запустить</button></div><div class="progress" style="margin:8px 0 0"><i id="pBar"></i></div><div class="dim mono" id="pMsg" style="font-size:11px"></div>`;
        if (cmp) {
          const Rc = RUNS[cmp];
          const diff = `<div class="sec"><h3>Выигрыш по блокам</h3><div class="dim" style="font-size:12px;margin:-4px 0 8px">${esc(R.label)} относительно «${esc(Rc.label)}»</div><table class="list">${BLK.map(
            ([k, l]) => {
              const dv = blockVal(R.score, k) - blockVal(Rc.score, k);
              return `<tr><td>${l}</td><td class="mono ${dv > 0.005 ? "ok" : dv < -0.005 ? "bad" : "dim"}" style="text-align:right">${dv > 0 ? "+" : ""}${dv.toFixed(2)}</td></tr>`;
            },
          ).join(
            "",
          )}<tr><td><b>Итог сценария</b></td><td class="mono" style="text-align:right"><b>${(R.score.total - Rc.score.total > 0 ? "+" : "") + (R.score.total - Rc.score.total).toFixed(2)}</b></td></tr></table></div>`;
          left2.innerHTML =
            `<div class="sec"><h3>Сравнить с</h3><select class="sel" id="cmpSel" style="width:100%">${others.map((k) => `<option value="${esc(k)}" ${k === cmp ? "selected" : ""}>${optLabel(k)}</option>`).join("")}</select></div>` +
            card(cmp, "var(--cmp)", diff);
          left2.querySelector("#cmpSel").addEventListener("change", (e) => {
            S.compare = e.target.value;
            S.t = 0; // другой прогон или режим — время в начало, пауза
            S.playing = false;
            openRun();
          });
          $("#cap2").innerHTML = `<b style="color:var(--cmp)">● ${esc(Rc.label)}</b> · seed ${Rc.seed}`;
        } else {
          left2.innerHTML = `<div class="sec"><h3>Сравнить с</h3><div class="empty">Другого прогона этого сценария пока нет. Запустите второй контроллер на том же seed — он появится здесь.</div>${pairLaunch}</div>`;
          $("#cap2").innerHTML = `<span>нет прогона для сравнения</span>`;
        }
        $("#cap1").innerHTML = `<b style="color:var(--accent)">● ${esc(R.label)}</b> · seed ${R.seed}`;
      } else {
        left.innerHTML = `<div class="sec"><h3>Прогон</h3><div class="kv"><dt>Сценарий</dt><dd>${runTitle(S.primary)}</dd><dt>Контроллер</dt><dd>${esc(R.label)} <span class="tip" tabindex="0" data-tip="${TIP[R.label] || ""}">?</span></dd><dt>Seed</dt><dd class="mono">${R.seed}</dd><dt>Длительность</dt><dd class="mono">${fmtT(derive(S.primary).tEnd)}</dd><dt>Шаг контроллера</dt><dd class="mono">${(R.step_ms.mean || 0).toFixed(2)} мс</dd></div>
          <div class="reseed"><span class="dim">Прогнать заново с seed</span><input class="sel mono" id="reSeed" value="${R.seed + 1}"><button class="btn small" id="reGo" ${ARM.canRun && scenInfo(R.scenario) ? "" : "disabled"}>Запустить</button></div><div class="progress" style="margin:8px 0 0"><i id="lBar"></i></div><div class="dim mono" id="lMsg" style="font-size:11px">${ARM.canRun ? "" : esc(ARM.reason)}</div></div>
          <div class="sec"><h3><span>Счёт сценария <span class="tip" tabindex="0" data-tip="${SCORE_TIP}">?</span></span>${cmp ? `<span style="color:var(--cmp);text-transform:none;letter-spacing:0">vs ${esc(RUNS[cmp].label)}</span>` : ""}</h3>${scoreHTML(S.primary, cmp)}</div>
          <div class="sec"><h3>Прогоны</h3><div class="run-list">${runListHTML()}</div></div>`;
        $("#cap1").innerHTML =
          `<b>${runTitle(S.primary)}</b> · ${esc(R.label)} · seed ${R.seed}${cmp ? ` &nbsp;<b style="color:var(--cmp)">● ${esc(RUNS[cmp].label)}</b>` : ""}`;
      }
      bindLeft();
      renderRight();
      const on = left.querySelector(".run.on");
      if (on) on.scrollIntoView({ block: "nearest" });
      if (OPEN.job) paintOpenJob();
    }
    function renderRight() {
      if (!ready(S.primary)) return;
      const bindSeek = () =>
        right
          .querySelectorAll("[data-seek]")
          .forEach((tr) => tr.addEventListener("click", () => seek(+tr.dataset.seek, !!tr.dataset.pause)));
      if (S.tab === "cmp" && ready(S.compare)) {
        const a = S.primary,
          b = S.compare;
        right.innerHTML = `<div class="sec"><h3>Сейчас · ${fmtT(S.t)}</h3><div id="now">${nowHTML([a, b])}</div></div>
          <div class="sec"><h3><span style="color:var(--accent)">● Журнал рейсов · ${esc(RUNS[a].label)}</span><span class="dim" style="text-transform:none;letter-spacing:0">можно выбрать</span></h3>${tripsHTML(a)}</div>
          <div class="sec"><h3><span style="color:var(--cmp)">● Журнал рейсов · ${esc(RUNS[b].label)}</span></h3>${tripsHTML(b)}</div>
          <div class="sec"><h3><span style="color:var(--accent)">● Остановки и штрафы</span><span class="dim" style="text-transform:none;letter-spacing:0">можно выбрать</span></h3>${eventsHTML(a)}</div>
          <div class="sec"><h3><span style="color:var(--cmp)">● Остановки и штрафы</span></h3>${eventsHTML(b)}</div>`;
        return bindSeek();
      }
      right.innerHTML = `<div class="sec"><h3>Сейчас · ${fmtT(S.t)}</h3><div id="now">${nowHTML(keysMain())}</div></div>
        <div class="sec"><h3>Журнал рейсов <span class="dim" style="text-transform:none;letter-spacing:0">можно выбрать</span></h3><div id="trips">${tripsHTML(S.primary)}</div></div>
        <div class="sec"><h3>Остановки и штрафы <span class="dim" style="text-transform:none;letter-spacing:0">можно выбрать</span></h3><div id="evs">${eventsHTML(S.primary)}</div></div>`;
      bindSeek();
    }
    let lastRight = 0;
    function tickRight() {
      const now = performance.now();
      if (S.playing && now - lastRight < 120) return;
      lastRight = now;
      const keys = S.tab === "cmp" ? [S.primary, S.compare] : keysMain();
      const n = $("#now");
      if (n) n.innerHTML = nowHTML(keys.filter(Boolean));
      const h = right.querySelector("h3");
      if (h) h.textContent = "Сейчас · " + fmtT(S.t);
    }

    /* запуск одного прогона из панели прогона: «заново с seed» и «пара для сравнения» */
    const OPEN = { job: null, role: "", bar: "", msg: "" };
    function paintOpenJob() {
      const j = JOBS[OPEN.job];
      const bar = $("#" + OPEN.bar),
        msg = $("#" + OPEN.msg);
      if (!j) return;
      if (bar) bar.style.width = (j.state === "queued" ? 3 : j.p || 0) + "%";
      if (!msg) return;
      msg.title = j.cmd || "";
      if (j.state === "queued") msg.textContent = "в очереди…";
      else if (j.state === "run")
        msg.textContent = "прогон… " + Math.round(j.p || 0) + "% · " + j.scenario + ", seed " + j.seed;
      else if (j.state === "error") msg.innerHTML = `<span class="bad">ошибка: ${esc(j.error || "")}</span>`;
      else msg.textContent = "готово · " + j.scenario + " · " + (j.total || 0).toFixed(2);
    }
    async function runOne(scenario, ctrl, seed, role, bar, msg) {
      Object.assign(OPEN, { job: null, role, bar, msg });
      try {
        const ids = await launchJobs(scenario, [ctrl], [seed]);
        OPEN.job = ids[0];
        paintOpenJob();
      } catch (e) {
        const m = $("#" + msg);
        if (m) m.innerHTML = `<span class="bad">${esc(e.message)}</span>`;
      }
    }
    hooks.push((fresh) => {
      if (!OPEN.job) return;
      const j = JOBS[OPEN.job];
      paintOpenJob();
      if (j && fresh.some((f) => f.id === j.id)) {
        const role = OPEN.role;
        OPEN.job = null;
        if (S.tab !== "run" && S.tab !== "cmp") return;
        if (role === "compare") S.compare = j.key;
        else {
          S.primary = j.key;
          S.t = 0;
        }
        openRun();
      } else if (j && j.state === "error") OPEN.job = null;
    });
    // прогоны, заменённые перезапуском, перечитать; новые — показать в списке
    hooks.push((fresh) => {
      if (!fresh.length) return;
      const wasEmpty = !S.primary;
      if (wasEmpty && RUN_ORDER.length) S.primary = RUN_ORDER[0];
      if (S.tab === "run" || S.tab === "cmp") {
        if (wasEmpty || fresh.some((j) => j.key === S.primary || j.key === S.compare)) openRun();
        else {
          const rl = left.querySelector(".run-list");
          if (rl) {
            rl.innerHTML = runListHTML();
            bindRunList();
          }
        }
      }
    });

    // переключатель «Показать сценарии-ограничения»: списки прогонов, история и «Сравнить с»
    document.addEventListener("change", (e) => {
      if (!e.target.matches || !e.target.matches("[data-limits]")) return;
      S.showLimits = e.target.checked;
      try {
        localStorage.setItem("arm.showLimits", S.showLimits ? "1" : "0");
      } catch (err) {
        /* только на эту сессию */
      }
      if (S.tab === "launch") renderLaunch();
      else renderPanels();
    });
    function bindRunList() {
      left.querySelectorAll("[data-run]").forEach((b) =>
        b.addEventListener("click", (e) => {
          if (e.target.classList.contains("tip")) return;
          S.primary = b.dataset.run;
          S.t = 0; // другой прогон или режим — время в начало, пауза
          S.playing = false;
          if (S.compare && (S.compare === S.primary || RUNS[S.compare].scenario !== RUNS[S.primary].scenario))
            S.compare = S.tab === "cmp" ? pairFor(S.primary) : null;
          openRun();
        }),
      );
    }
    function bindLeft() {
      bindRunList();
      const rg = left.querySelector("#reGo");
      if (rg)
        rg.addEventListener("click", () => {
          const R = RUNS[S.primary];
          const seed = parseInt(left.querySelector("#reSeed").value, 10);
          if (!(seed >= 0)) return;
          runOne(R.scenario, R.ctrl, seed, "primary", "lBar", "lMsg");
        });
      const pg = left2.querySelector("#pairGo");
      if (pg)
        pg.addEventListener("click", () => {
          const R = RUNS[S.primary];
          const other = CTRLS.find((c) => c.key !== R.ctrl);
          if (other) runOne(R.scenario, other.key, R.seed, "compare", "pBar", "pMsg");
        });
    }
    function setTab(tab) {
      S.tab = tab;
      const isL = tab === "launch",
        isB = tab === "build";
      main.hidden = isL || isB;
      bottom.hidden = isL || isB;
      launchHost.hidden = !isL;
      buildHost.hidden = !isB;
      document
        .querySelectorAll(".tab")
        .forEach((t) => t.classList.toggle("on", t.dataset.tab === (isL ? "launch" : isB ? "build" : "run")));
      $("#modeSeg").hidden = isL || isB;
      if (isB) {
        S.playing = false;
        openBuilder();
        return;
      }
      if (isL) {
        S.playing = false;
        renderLaunch();
        return;
      }
      if (tab === "cmp") {
        main.classList.add("cmp5");
        view2.hidden = false;
        left2.hidden = false;
        $("#layers").hidden = true;
      } else {
        S.compare = null;
        main.classList.remove("cmp5");
        view2.hidden = true;
        left2.hidden = true;
        $("#layers").hidden = false;
      }
      right.hidden = false;
      document.querySelectorAll("#modeSeg button").forEach((x) => x.classList.toggle("on", x.dataset.mode === tab));
      renderPanels();
      requestAnimationFrame(() => {
        map1.reset();
        map2.reset();
        emit();
      });
      openRun();
    }

    /* ---------- конструктор сценария ---------- */
    const ROUTES = {}; // ключ «warehouse>shop_a>warehouse» -> маршрут из реального сценария
    const routeKey = (ms) => (ms.length ? [ms[0].from].concat(ms.map((m) => m.to)).join(">") : "");
    function buildRoutes() {
      const pref = ["04_busy_yard", "02_gnss_shadow", "03_fog_snow", "01_clear"];
      const ids = pref
        .filter((id) => SCENS[id])
        .concat(
          Object.keys(SCENS)
            .sort()
            .filter((id) => pref.indexOf(id) < 0),
        );
      ids.forEach((id) => {
        const d = SCENS[id],
          k = routeKey(d.missions || []);
        if (!k || ROUTES[k]) return;
        ROUTES[k] = { ru: k.split(">").map(ptRu).join(" → "), src: id, missions: d.missions, duration: d.duration_s };
      });
    }
    buildRoutes();
    const firstRoute = ROUTES["warehouse>shop_a>warehouse"]
      ? "warehouse>shop_a>warehouse"
      : Object.keys(ROUTES)[0] || "";
    const B = { tool: "ped", peds: [], cur: null, pallets: [], boxes: [], removed: [], route: firstRoute, missions: null, duration: null, snow: false,
      fog: [120, 200], fogOn: true, gnss: [0, 0], gnssOn: false, name: "Мой сценарий 1", src: "new", id: null, ro: false, msg: null, busy: false, map: null, det: false, generator: null, extraEv: [] }; // prettier-ignore
    const customs = () => SCEN_LIST.filter((s) => s.group === "Свои");
    const curMissions = () => B.missions || (ROUTES[B.route] ? ROUTES[B.route].missions : []);
    const curMap = () => B.map || BASEMAP; // карта самого сценария: у скрытоподобных своя тень ГНСС
    const FULL = {}; // id -> сценарий целиком (с картой), подгружается при открытии в конструкторе
    function loadState(st, src, ro) {
      Object.assign(B, JSON.parse(JSON.stringify(st)), { cur: null, src, ro, msg: null });
    }
    function stateFromScenario(id) {
      const d = FULL[id];
      const fog = d.events.find((e) => e.type === "fog_bank"),
        out = d.events.find((e) => e.type === "gnss_outage");
      const isCustom = (scenInfo(id) || {}).group === "Свои";
      return {
        name: isCustom ? d.description || id : el("span", null, scenRu(id)).textContent,
        id: isCustom ? id : null,
        route: routeKey(d.missions),
        missions: d.missions,
        duration: d.duration_s,
        snow: !!(d.weather || {}).snow,
        fogOn: !!fog, fog: fog ? [fog.t1, fog.t2] : [120, 200],
        gnssOn: !!out, gnss: out ? [out.t1, out.t2] : [0, 0],
        peds: d.pedestrians.map((p) => ({ inatt: !!p.inattentive, pts: p.waypoints, speed: p.speed, t0: p.t_start || 0, loop: p.loop !== false })),
        pallets: d.events.filter((e) => e.type === "object_dropped").map((e) => ({ x: e.x, y: e.y, t: e.t, r: e.r })),
        removed: d.map_patches.filter((q) => q.op === "remove").map((q) => q.id),
        boxes: d.map_patches.filter((q) => q.op === "add").map((q) => ({ poly: q.polygon, id: q.id })),
        map: d.map || null, det: !!d.provide_detections, generator: d.generator || null,
        // вторые и следующие полосы тумана и окна без спутника: в форме одна строка, остальные сохраняются как есть
        extraEv: d.events.filter((e) => (e.type === "fog_bank" && e !== fog) || (e.type === "gnss_outage" && e !== out)),
      }; // prettier-ignore
    }
    const TOOLS = [
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
      [
        "pallet",
        "Поддон",
        "Появится на дороге в заданный момент. Тележка должна заметить и объехать или остановиться.",
      ],
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
    let bmap = null;
    function bOverlay(ctx, X, Y, sc) {
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
        ctx.strokeStyle = C.bad;
        ctx.setLineDash([4, 3]);
        ctx.lineWidth = 1.5;
        ctx.stroke();
        ctx.setLineDash([]);
      });
      B.boxes
        .filter((bx) => bx.poly)
        .forEach((bx) => {
          ctx.beginPath();
          bx.poly.forEach(([x, y], k) => (k ? ctx.lineTo(X(x), Y(y)) : ctx.moveTo(X(x), Y(y))));
          ctx.closePath();
          ctx.fillStyle = "rgba(196,89,90,0.3)";
          ctx.fill();
          ctx.strokeStyle = C.bad;
          ctx.lineWidth = 1.5;
          ctx.stroke();
        });
      B.boxes
        .filter((bx) => !bx.poly)
        .forEach((bx) => {
          ctx.fillStyle = "rgba(196,89,90,0.3)";
          ctx.strokeStyle = C.bad;
          ctx.lineWidth = 1.5;
          ctx.fillRect(X(bx.x - 3), Y(bx.y + 1.25), 6 * sc, 2.5 * sc);
          ctx.strokeRect(X(bx.x - 3), Y(bx.y + 1.25), 6 * sc, 2.5 * sc);
        });
      B.pallets.forEach((p) => {
        ctx.beginPath();
        ctx.arc(X(p.x), Y(p.y), Math.max(4, (p.r || 0.4) * sc), 0, Math.PI * 2);
        ctx.fillStyle = "#8a6b3f";
        ctx.fill();
        ctx.strokeStyle = C.warn;
        ctx.lineWidth = 1.5;
        ctx.stroke();
        ctx.font = "500 10px JetBrains Mono, monospace";
        ctx.fillStyle = C.warn;
        ctx.textAlign = "left";
        ctx.fillText("t=" + p.t + " с", X(p.x) + 8, Y(p.y) - 6);
      });
      B.peds.concat(B.cur ? [B.cur] : []).forEach((pd) => {
        const col = pd.inatt ? C.bad : "#e8eaed";
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
    function bClick(x, y) {
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
      renderBuilderSide();
      bmap.draw();
    }
    function finishPed() {
      if (B.cur && B.cur.pts.length >= 2) B.peds.push(B.cur);
      B.cur = null;
    }
    function checks() {
      const out = [];
      const ms = curMissions();
      if (!ms.length) return [["warn", "Нет ни одного сценария с маршрутом: укажите папку симулятора (флаг --sim)"]];
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
            extra
              .map((e) => (e.type === "fog_bank" ? "туман " : "нет спутника ") + e.t1 + "–" + e.t2 + " с")
              .join(", "),
        ]);
      if (B.cur && B.cur.pts.length < 2)
        out.push(["dim", "Пешеход с одной точкой пути не сохранится — поставьте вторую"]);
      return out;
    }
    function renderBuilderSide() {
      const l = buildHost.querySelector(".bleft"),
        r = buildHost.querySelector(".bright");
      const opt = (id) =>
        `<option value="sc:${esc(id)}" ${B.src === "sc:" + id ? "selected" : ""}>${scenRu(id)}</option>`;
      const libOpts = `<option value="new" ${B.src === "new" ? "selected" : ""}>+ Новый сценарий</option>
        <optgroup label="Свои">${customs().map((c) => opt(c.id)).join("") || `<option disabled>пока нет</option>`}</optgroup>` +
        GROUPS.filter((g) => g !== "Свои").map((g) => {
          const ids = SCEN_LIST.filter((s) => s.group === g).map((s) => s.id);
          return ids.length ? `<optgroup label="${g}">${ids.map(opt).join("")}</optgroup>` : "";
        }).join(""); // prettier-ignore
      const routeOpts = Object.entries(ROUTES)
        .map(([k, v]) => `<option value="${esc(k)}" ${k === B.route ? "selected" : ""}>${v.ru}</option>`)
        .join("");
      l.innerHTML = `<div class="sec"><h3>Открыть сценарий</h3><select class="sel" id="bLib" style="width:100%">${libOpts}</select>
          ${B.ro ? `<div class="lock"><svg viewBox="0 0 16 16"><rect x="3" y="7" width="10" height="7" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M5.5 7V5a2.5 2.5 0 015 0v2" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>Только просмотр — сценарий ${(scenInfo(B.src.slice(3)) || {}).group === "Открытые" || (scenInfo(B.src.slice(3)) || {}).group === "Учебные" ? "организаторов" : "из набора проверки"} не меняется</div><button class="btn" id="bCopy" style="width:100%;margin-top:8px">Создать копию и изменить</button>` : ""}</div>
        <div class="sec"><h3>Название</h3><input class="sel" id="bName" value="${esc(B.name)}" style="width:100%" ${B.ro ? "disabled" : ""}></div>
        <div class="sec"><h3>Маршрут</h3><select class="sel" id="bRoute" style="width:100%" ${B.ro ? "disabled" : ""}>${routeOpts}</select></div>
        <div class="${B.ro ? "ro" : ""}"><div class="sec"><h3>Погода и связь</h3>
          <label class="toggle ${B.snow ? "on" : ""}"><input type="checkbox" id="bSnow" ${B.snow ? "checked" : ""}><span class="sw"></span>Снег весь прогон</label>
          <div class="wrow"><label class="toggle ${B.fogOn ? "on" : ""}"><input type="checkbox" id="bFog" ${B.fogOn ? "checked" : ""}><span class="sw"></span>Туман</label><input class="sel mono" id="bF1" value="${B.fog[0]}"><span class="dim">–</span><input class="sel mono" id="bF2" value="${B.fog[1]}"><span class="dim">с</span></div>
          <div class="wrow"><label class="toggle ${B.gnssOn ? "on" : ""}"><input type="checkbox" id="bG" ${B.gnssOn ? "checked" : ""}><span class="sw"></span>Нет спутника</label><input class="sel mono" id="bG1" value="${B.gnss[0]}"><span class="dim">–</span><input class="sel mono" id="bG2" value="${B.gnss[1]}"><span class="dim">с</span></div>
        </div>
        <div class="sec"><h3>Добавить на карту</h3><div class="tools">${TOOLS.map(([k, lbl, tip]) => `<button class="toolb ${B.tool === k ? "on" : ""}" data-tool="${k}"><span class="ic ic-${k}"></span>${lbl}<span class="tip" tabindex="0" data-tip="${tip}">?</span></button>`).join("")}</div>
          <div class="dim" style="font-size:12px;margin-top:8px">${B.tool.indexOf("ped") === 0 ? (B.cur ? `Точек пути: ${B.cur.pts.length}. Продолжайте кликать или <button class="btn small" id="bPedDone">Готово</button>` : "Кликните по карте, чтобы поставить первую точку пути.") : "Кликните по карте."}</div></div></div>`;
      const objs = [];
      B.peds.forEach((p, i) =>
        objs.push([
          `${p.inatt ? "Невнимательный пешеход" : "Пешеход"} ${i + 1}`,
          `${p.pts.length} точек · ${p.speed} м/с`,
          "peds",
          i,
        ]),
      );
      B.pallets.forEach((p, i) => objs.push([`Поддон ${i + 1}`, `появится на ${p.t} с`, "pallets", i]));
      B.boxes.forEach((b, i) => objs.push([`Препятствие ${i + 1}`, "нет на карте", "boxes", i]));
      B.removed.forEach((id, i) => objs.push([`Снесено: ${buildRu(id)}`, "есть на карте, нет в мире", "removed", i]));
      const msg = B.msg
        ? `<div class="${B.msg[0] === "bad" ? "lock" : "ck ok"}" style="margin-top:10px">${B.msg[0] === "bad" ? "" : "<span>✓</span>"}${esc(B.msg[1])}</div>`
        : "";
      r.innerHTML = `<div class="sec"><h3>Объекты сценария</h3>${objs.length ? `<div class="objs">${objs.map(([a, b, arr, i]) => `<div class="obj"><div><div>${a}</div><div class="dim" style="font-size:12px">${b}</div></div>${B.ro ? "" : `<button class="btn small" data-del="${arr}:${i}">✕</button>`}</div>`).join("")}</div>` : `<div class="dim">Пока пусто. Выберите инструмент слева и кликните по карте.</div>`}</div>
        <div class="sec"><h3>Проверка сценария <span class="tip" tabindex="0" data-tip="Быстрая проверка по тем же правилам, по которым организаторы допускают скрытые сценарии. При сохранении сценарий дополнительно проверяет сам симулятор.">?</span></h3><div class="checks">${checks()
          .map(([c, t]) => `<div class="ck ${c}"><span>${c === "warn" ? "!" : c === "ok" ? "✓" : "·"}</span>${t}</div>`)
          .join("")}</div></div>
        <div class="sec"><button class="btn primary go" id="bRun" ${ARM.canRun && !B.busy ? "" : "disabled"}>${B.busy ? "Сохраняю…" : "▶ Запустить: наш контроллер и Baseline"}</button>${B.ro ? "" : `<button class="btn" id="bKeep" style="width:100%;margin-top:8px" ${B.busy || !ARM.canRun ? "disabled" : ""} title="${ARM.canRun ? "" : esc(ARM.reason)}">Сохранить в «Свои»</button>`}<button class="btn" id="bSave" style="width:100%;margin-top:8px">Скачать сценарий (JSON)</button>${msg}</div>`;
      bindBuilder();
    }
    function newState() {
      return { peds: [], pallets: [], boxes: [], removed: [], route: firstRoute, missions: null, duration: null, snow: false, fog: [120, 200], fogOn: false,
        gnss: [0, 0], gnssOn: false, name: "Мой сценарий " + (customs().length + 1), id: null, map: null, det: false, generator: null, extraEv: [] }; // prettier-ignore
    }
    const bcapEdit = `<b>Конструктор сценария</b> · выберите инструмент и кликайте по карте`;
    async function openScenario(v) {
      if (v === "new") loadState(newState(), "new", false);
      else {
        const id = v.slice(3);
        try {
          if (!FULL[id]) FULL[id] = (await api("/api/scenario/" + encodeURIComponent(id))).scenario;
        } catch (e) {
          B.msg = ["bad", "Не удалось открыть сценарий: " + e.message];
          renderBuilderSide();
          return;
        }
        loadState(stateFromScenario(id), v, (scenInfo(id) || {}).group !== "Свои");
      }
      buildHost.querySelector("#bcap").innerHTML = B.ro ? `<b>${esc(B.name)}</b> · только просмотр` : bcapEdit;
      renderBuilderSide();
      bmap.draw();
    }
    function bindBuilder() {
      const H = buildHost;
      H.querySelector("#bLib").addEventListener("change", (e) => openScenario(e.target.value));
      const cp = H.querySelector("#bCopy");
      if (cp)
        cp.addEventListener("click", () => {
          Object.assign(B, { ro: false, src: "new", id: null, name: "Копия: " + B.name, msg: null });
          H.querySelector("#bcap").innerHTML = bcapEdit;
          renderBuilderSide();
        });
      const kp = H.querySelector("#bKeep");
      if (kp) kp.addEventListener("click", () => saveCustom().catch(() => {}));
      H.querySelector("#bSave").addEventListener("click", () => saveJSON());
      H.querySelector("#bRun").addEventListener("click", () => runCustom());
      if (B.ro) return;
      H.querySelector("#bName").addEventListener("change", (e) => (B.name = e.target.value.trim() || B.name));
      H.querySelector("#bRoute").addEventListener("change", (e) => {
        B.route = e.target.value;
        B.missions = null;
        B.duration = null;
        renderBuilderSide();
        bmap.draw();
      });
      H.querySelector("#bSnow").addEventListener("change", (e) => {
        B.snow = e.target.checked;
        renderBuilderSide();
      });
      H.querySelector("#bFog").addEventListener("change", (e) => {
        B.fogOn = e.target.checked;
        renderBuilderSide();
      });
      H.querySelector("#bG").addEventListener("change", (e) => {
        B.gnssOn = e.target.checked;
        if (B.gnssOn && !B.gnss[1]) B.gnss = [60, 110];
        renderBuilderSide();
      });
      [["#bF1", "fog", 0], ["#bF2", "fog", 1], ["#bG1", "gnss", 0], ["#bG2", "gnss", 1]].forEach(([id, k, i]) =>
        H.querySelector(id).addEventListener("change", (e) => {
          B[k][i] = Math.max(0, +e.target.value || 0);
          renderBuilderSide();
        }),
      ); // prettier-ignore
      H.querySelectorAll("[data-tool]").forEach((b) =>
        b.addEventListener("click", (e) => {
          if (e.target.classList.contains("tip")) return;
          finishPed();
          B.tool = b.dataset.tool;
          renderBuilderSide();
          bmap.draw();
        }),
      );
      const pd = H.querySelector("#bPedDone");
      if (pd)
        pd.addEventListener("click", () => {
          finishPed();
          renderBuilderSide();
          bmap.draw();
        });
      H.querySelectorAll("[data-del]").forEach((b) =>
        b.addEventListener("click", () => {
          const [arr, i] = b.dataset.del.split(":");
          B[arr].splice(+i, 1);
          renderBuilderSide();
          bmap.draw();
        }),
      );
    }
    /** Сценарий amr-1.0 из состояния конструктора: карта и маршрут — из реальных сценариев. */
    function buildScenario() {
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
      const duration =
        B.duration || (ROUTES[B.route] && !B.missions ? ROUTES[B.route].duration : 0) || Math.round(sumDl + 15);
      const ev = [];
      if (B.fogOn && B.fog[0] < B.fog[1]) ev.push({ type: "fog_bank", t1: B.fog[0], t2: B.fog[1] });
      if (B.gnssOn && B.gnss[0] < B.gnss[1]) ev.push({ type: "gnss_outage", t1: B.gnss[0], t2: B.gnss[1] });
      (B.extraEv || []).forEach((e) => ev.push({ ...e }));
      B.pallets.forEach((p) => ev.push({ type: "object_dropped", t: p.t, x: p.x, y: p.y, r: p.r || 0.4 }));
      // id патчей: исходные сохраняются, новым — BOX_n, не совпадающий со зданиями и другими патчами
      const taken = new Set(map.buildings.map((b) => b.id).concat(B.boxes.map((b) => b.id).filter(Boolean), B.removed));
      let nb = 0;
      const freeId = () => {
        while (taken.has("BOX_" + ++nb));
        return "BOX_" + nb;
      };
      const patches = B.boxes
        .map((b) => ({ id: b.id || freeId(), op: "add", polygon: b.poly || [[b.x - 3, b.y - 1.25], [b.x + 3, b.y - 1.25], [b.x + 3, b.y + 1.25], [b.x - 3, b.y + 1.25]] }))
        .concat(B.removed.map((id) => ({ id, op: "remove" }))); // prettier-ignore
      const p0 = missions.length ? pts[missions[0].from] : null;
      const th = p0 ? Math.atan2(Math.sin(p0.heading + Math.PI), Math.cos(p0.heading + Math.PI)) : 0;
      const sc = {
        schema: "amr-1.0", name: B.id || "custom", description: B.name, dt: 0.1, duration_s: duration, hidden: false, provide_detections: !!B.det,
        weather: { snow: B.snow }, map, map_patches: patches,
        start: p0 ? { x: p0.x, y: p0.y, theta: +th.toFixed(6) } : { x: 0, y: 0, theta: 0 },
        missions,
        pedestrians: B.peds.map((p, i) => ({ id: "p" + (i + 1), waypoints: p.pts, speed: p.speed, inattentive: p.inatt, loop: p.loop !== false, t_start: p.t0 || 0 })),
        events: ev,
      }; // prettier-ignore
      if (B.generator) sc.generator = B.generator; // происхождение копии скрытоподобного сценария
      return sc;
    }
    async function saveJSON() {
      let body;
      if (B.ro) {
        // просмотр: исходный файл как есть, без пересборки
        const resp = await fetch("/api/scenario/" + encodeURIComponent(B.src.slice(3)) + "?raw=1");
        if (!resp.ok) {
          B.msg = ["bad", "сценарий не найден на сервере (" + resp.status + ")"];
          renderBuilderSide();
          return;
        }
        body = await resp.blob();
      } else body = new Blob([JSON.stringify(buildScenario(), null, 1)], { type: "application/json" });
      const name = (B.ro ? B.src.slice(3) : B.id || "custom_scenario") + ".json";
      const a = el("a");
      a.href = URL.createObjectURL(body);
      a.download = name;
      document.body.appendChild(a);
      a.click();
      setTimeout(() => a.remove(), 1000);
      renderBuilderSide();
      bmap.draw();
    }
    // токены правки своих сценариев: сервер перезаписывает сценарий только с токеном из первого сохранения
    const tokens = () => {
      try {
        return JSON.parse(localStorage.getItem("arm.customTokens") || "{}");
      } catch (e) {
        return {};
      }
    };
    const keepToken = (id, token) => {
      try {
        localStorage.setItem("arm.customTokens", JSON.stringify({ ...tokens(), [id]: token }));
      } catch (e) {
        /* без localStorage следующая правка сохранится как новый сценарий */
      }
    };
    async function saveCustom() {
      B.busy = true;
      B.msg = null;
      renderBuilderSide();
      try {
        const asked = B.id;
        const r = await api("/api/scenario", {
          id: asked,
          token: asked ? tokens()[asked] || null : null,
          scenario: buildScenario(),
        });
        keepToken(r.id, r.token);
        const d = await api("/api/scenario/" + encodeURIComponent(r.id));
        FULL[r.id] = d.scenario;
        SCENS[r.id] = d.scenario;
        const s = scenInfo(r.id);
        if (s) s.title = B.name;
        else SCEN_LIST.push({ id: r.id, group: "Свои", title: B.name });
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
        B.msg = ["bad", e.message];
        throw e;
      } finally {
        B.busy = false;
        renderBuilderSide();
        bmap.draw();
      }
    }
    async function runCustom() {
      let id;
      if (B.ro) id = B.src.slice(3);
      else {
        try {
          id = await saveCustom();
        } catch (e) {
          return;
        }
      }
      LS.scen = new Set([id]);
      LS.ctrl = new Set(CTRLS.map((c) => c.key));
      LS.seeds = "1";
      setTab("launch");
      await startBatch();
      renderLaunch();
    }
    function openBuilder() {
      if (!buildHost.firstChild) {
        buildHost.innerHTML = `<div class="bgrid"><aside class="panel bleft"></aside><section class="view" id="bview"><div class="cap" id="bcap">${bcapEdit}</div>${legendHTML("build", "build", false)}</section><aside class="panel right bright"></aside></div>`;
        bmap = MapView(buildHost.querySelector("#bview"), () => [], {
          editor: true,
          getMap: curMap,
          overlay: bOverlay,
          onClick: bClick,
        });
        // заготовка, чтобы новый сценарий не был пустым
        B.peds.push({
          inatt: false,
          pts: [
            [112, 158],
            [112, 141],
            [125, 141],
          ],
          speed: 1.0,
          t0: 0,
          loop: true,
        });
        B.peds.push({
          inatt: true,
          pts: [
            [150, 145],
            [150, 156],
            [160, 156],
          ],
          speed: 1.3,
          t0: 0,
          loop: true,
        });
        B.pallets.push({ x: 140, y: 152.2, t: 70, r: 0.4 });
        B.name = "Мой сценарий " + (customs().length + 1);
      }
      renderBuilderSide();
      requestAnimationFrame(() => bmap.reset());
    }

    /* ---------- вкладка «Запуск» ---------- */
    function renderLaunch() {
      launchHost.innerHTML = launchFullHTML();
      bindLaunch();
      paintQueue([]);
    }
    function paintQueue(fresh) {
      if (launchHost.hidden) return;
      const H = launchHost,
        q = H.querySelector("#queue");
      if (!q) return;
      const jobs = LS.jobs.map((id) => JOBS[id]).filter(Boolean);
      q.innerHTML = queueHTML();
      const n = jobs.length,
        done = jobs.filter((j) => j.state === "done" || j.state === "error").length;
      const run = jobs.filter((j) => j.state === "run");
      H.querySelector("#qBar").style.width = n
        ? (100 * (done + run.reduce((a, j) => a + (j.p || 0) / 100, 0))) / n + "%"
        : "0%";
      const left =
        (jobs.filter((j) => j.state === "queued").length * (ARM.avgS || 6)) / (ARM.parallel || 2) +
        run.reduce((a, j) => Math.max(a, j.left || 0), 0);
      const st = H.querySelector("#qStat");
      if (n && LS.running) st.textContent = `выполнено ${done} из ${n} · осталось ~${Math.max(1, Math.round(left))} с`;
      if (fresh.length || !LS.running) {
        H.querySelector("#hist").innerHTML = historyHTML();
      }
      if (LS.running && n && done === n) {
        LS.running = false;
        const errs = jobs.filter((j) => j.state === "error").length;
        st.innerHTML = `готово${errs ? ` · ошибок: ${errs}` : ""} · прогоны добавлены во вкладку «Прогоны» <button class="btn small" id="toRuns">Перейти</button>`;
        const tr = H.querySelector("#toRuns");
        tr.addEventListener("click", () => {
          const first = jobs.find((j) => j.state === "done" && RUNS[j.key]);
          if (first) S.primary = first.key;
          S.t = 0;
          const pair =
            first &&
            jobs.find(
              (j) =>
                j.state === "done" && j.key !== first.key && j.scenario === first.scenario && j.seed === first.seed,
            );
          if (pair && lastMode === "cmp") S.compare = pair.key;
          setTab(lastMode);
        });
      }
      const g = H.querySelector("#lGo");
      if (g) {
        g.disabled = LS.running || !nJobs() || !ARM.canRun;
        g.textContent = goLabel();
      }
    }
    hooks.push((fresh) => paintQueue(fresh));
    // «Открыть» и «Сравнить» в очереди и истории: один обработчик на всю вкладку
    launchHost.addEventListener("click", (e) => {
      const o = e.target.closest("[data-open]"),
        c = e.target.closest("[data-cmpopen]");
      if (!o && !c) return;
      S.primary = o ? o.dataset.open : c.dataset.cmpopen;
      S.compare = null;
      S.t = 0;
      S.playing = false;
      lastMode = o ? "run" : "cmp";
      setTab(lastMode);
    });
    function bindLaunch() {
      const H = launchHost;
      H.querySelectorAll("[data-scen]").forEach((c) =>
        c.addEventListener("click", (e) => {
          if (LS.running || e.target.classList.contains("tip")) return;
          const id = c.dataset.scen;
          if (LS.scen.has(id)) LS.scen.delete(id);
          else LS.scen.add(id);
          renderLaunch();
        }),
      );
      H.querySelectorAll("[data-ctrl]").forEach((c) =>
        c.addEventListener("click", (e) => {
          if (LS.running || e.target.classList.contains("tip")) return;
          const id = c.dataset.ctrl;
          if (LS.ctrl.has(id)) LS.ctrl.delete(id);
          else LS.ctrl.add(id);
          renderLaunch();
        }),
      );
      H.querySelector("#lSeeds").addEventListener("change", (e) => {
        LS.seeds = e.target.value;
        renderLaunch();
      });
      const go = H.querySelector("#lGo");
      if (go)
        go.addEventListener("click", async () => {
          go.disabled = true;
          await startBatch();
          renderLaunch();
        });
    }

    document
      .querySelectorAll(".tab")
      .forEach((t) => t.addEventListener("click", () => setTab(t.dataset.tab === "run" ? lastMode : t.dataset.tab)));
    document.querySelectorAll("#modeSeg button").forEach((b) =>
      b.addEventListener("click", () => {
        lastMode = b.dataset.mode;
        S.t = 0; // другой прогон или режим — время в начало, пауза
        S.playing = false;
        setTab(b.dataset.mode);
      }),
    );
    view.querySelectorAll("[data-layer]").forEach((c) =>
      c.addEventListener("change", () => {
        S.layers[c.dataset.layer] = c.checked;
        emit();
      }),
    );
    $("#follow").addEventListener("change", (e) => {
      S.follow = e.target.checked;
      emit();
    });
    $("#play").addEventListener("click", () => {
      if (S.t >= tMax()) S.t = 0;
      S.playing = !S.playing;
      emit();
    });
    bottom.querySelectorAll("[data-sp]").forEach((b) =>
      b.addEventListener("click", () => {
        S.speed = +b.dataset.sp;
        bottom.querySelectorAll("[data-sp]").forEach((x) => x.classList.toggle("on", x === b));
      }),
    );
    $("#expTrips").addEventListener("click", exportTrips);
    $("#expEv").addEventListener("click", exportEvents);
    window.addEventListener("keydown", (e) => {
      if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT" || !main.offsetParent) return;
      if (e.code === "Space") {
        e.preventDefault();
        S.playing = !S.playing;
        emit();
      }
      if (e.code === "ArrowRight") seek(S.t + (e.shiftKey ? 10 : 1), false);
      if (e.code === "ArrowLeft") seek(S.t - (e.shiftKey ? 10 : 1), false);
    });
    let lastTrips = -1;
    onChange(() => {
      $("#play").textContent = S.playing ? "❚❚" : "▶";
      $("#time").textContent = ready(S.primary) ? fmtT(S.t) + " / " + fmtT(tMax()) : "—";
      map1.draw();
      if (S.tab === "cmp") map2.draw();
      tracks.draw();
      tickRight();
      // таблицы справа перерисовываем, когда сменился двухсекундный отрезок
      const k = Math.floor(S.t / 2);
      if (!S.playing && k !== lastTrips) {
        lastTrips = k;
        renderRight();
      }
    });
    let prev = performance.now();
    function loop(now) {
      const dt = (now - prev) / 1000;
      prev = now;
      if (S.playing) {
        S.t += dt * S.speed;
        if (S.t >= tMax()) {
          S.t = tMax();
          S.playing = false;
        }
        emit();
      }
      requestAnimationFrame(loop);
    }

    // начальное состояние; ссылка вида #run=<id>&t=62&mode=cmp&cmp=<id> или #tab=launch, #tab=build&scen=<id>
    const hp = new URLSearchParams(location.hash.replace(/^#/, ""));
    const pick = hp.get("run");
    S.primary = pick && RUNS[pick] ? pick : RUNS["04_busy_yard__s1"] ? "04_busy_yard__s1" : RUN_ORDER[0] || null;
    if (hp.get("cmp") && RUNS[hp.get("cmp")]) S.compare = hp.get("cmp");
    S.t = +hp.get("t") || 0;
    const mode = hp.get("mode") === "cmp" ? "cmp" : "run";
    lastMode = mode;
    const tab = hp.get("tab");
    if (tab === "launch") setTab("launch");
    else if (tab === "build") {
      setTab("build");
      const sid = hp.get("scen");
      if (sid && SCENS[sid]) openScenario("sc:" + sid);
    } else setTab(mode);
    // задания, начатые до перезагрузки страницы, показываем в очереди
    api("/api/jobs")
      .then((list) => {
        list.forEach((j) => {
          JOBS[j.id] = j;
          if (j.state === "done" || j.state === "error") handled.add(j.id);
        });
        const active = list.filter((j) => j.state === "queued" || j.state === "run").map((j) => j.id);
        if (active.length) {
          LS.jobs = active;
          LS.running = true;
          startPolling();
        }
      })
      .catch(() => {});
    emit();
    requestAnimationFrame(loop);
  }

  // всплывающая подсказка поверх окна: справа от «?», не выходит за край экрана
  let tipBox = null;
  function showTip(t) {
    hideTip();
    const txt = t.dataset.tip;
    if (!txt) return;
    tipBox = el("div", "tipbox");
    tipBox.textContent = txt;
    document.body.appendChild(tipBox);
    const r = t.getBoundingClientRect(),
      bw = tipBox.offsetWidth,
      bh = tipBox.offsetHeight;
    let x = r.right + 10,
      y = r.top - 6;
    if (x + bw > window.innerWidth - 8) x = r.left - bw - 10;
    if (x < 8) x = 8;
    if (y + bh > window.innerHeight - 8) y = window.innerHeight - bh - 8;
    tipBox.style.left = x + "px";
    tipBox.style.top = Math.max(8, y) + "px";
  }
  function hideTip() {
    if (tipBox) {
      tipBox.remove();
      tipBox = null;
    }
  }
  document.addEventListener("mouseover", (e) => {
    const t = e.target.closest(".tip");
    if (t) showTip(t);
  });
  document.addEventListener("mouseout", (e) => {
    if (e.target.closest(".tip")) hideTip();
  });
  document.addEventListener("focusin", (e) => {
    if (e.target.classList && e.target.classList.contains("tip")) showTip(e.target);
  });
  document.addEventListener("focusout", hideTip);
  document.addEventListener("DOMContentLoaded", build);
})();
