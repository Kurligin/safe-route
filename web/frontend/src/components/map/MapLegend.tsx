import { useState } from "react";

const ITEMS: Record<string, string> = {
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
const SETS: Record<"run" | "build", [string, string[]][]> = {
  run: [
    [
      "Объекты",
      ["bot", "cmpbot", "est", "trail", "esttrail", "path", "ped", "near", "pallet", "box", "removed", "dock"],
    ],
  ],
  build: [["Объекты", ["route", "ped", "inatt", "pallet", "box", "removed", "dock"]]],
};
const ZONES: [string, string[]] = ["Зоны", ["shadow", "speed", "people", "forbidden"]];

function stored(id: string, def: boolean): boolean {
  // ключ v2: после смены умолчания на «свёрнута» старые сохранённые состояния не действуют
  try {
    const v = localStorage.getItem("arm.legend2." + id);
    return v === null ? def : v === "1";
  } catch {
    return def;
  }
}

/** Легенда карты: сворачиваемая плашка в левом нижнем углу, состояние запоминается. */
export function MapLegend({ kind, id, openByDefault }: { kind: "run" | "build"; id: string; openByDefault: boolean }) {
  const [open, setOpen] = useState(() => stored(id, openByDefault));
  const toggle = () => {
    setOpen(!open);
    try {
      localStorage.setItem("arm.legend2." + id, open ? "0" : "1");
    } catch {
      /* без localStorage — только на эту сессию */
    }
  };
  return (
    <div className={"mlegend" + (open ? " open" : "")} data-legend={id}>
      <button className="mlegend-h" type="button" aria-expanded={open} onClick={toggle}>
        <span>Легенда</span>
        <svg viewBox="0 0 10 6">
          <path d="M1 5l4-4 4 4" fill="none" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      </button>
      <div className="mlegend-b">
        {SETS[kind].concat([ZONES]).map(([g, keys]) => [
          <div className="lg-g" key={g}>
            {g}
          </div>,
          ...keys.map((k) => (
            <span className="lg" key={g + k}>
              <i className={"sw sw-" + k} />
              {ITEMS[k]}
            </span>
          )),
        ])}
      </div>
    </div>
  );
}
