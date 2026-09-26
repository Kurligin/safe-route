import { api } from "../api/client";
import { download } from "../lib/download";
import { app, setMode, setTab, useApp } from "../store/app";

/** Верхняя панель: вкладки, переключатель «Один прогон / Сравнение», выгрузка CSV. */
export function TopBar() {
  const tab = useApp((s) => s.tab);
  const lastMode = useApp((s) => s.lastMode);
  const onRuns = tab === "run" || tab === "cmp";
  const csv = (kind: "trips" | "stops") => {
    const k = app.get().primary;
    if (!k || !app.get().runs[k]?.ticks) return;
    download(kind === "trips" ? api.tripsCsvUrl(k) : api.stopsCsvUrl(k));
  };
  const tabBtn = (key: "run" | "launch" | "build", label: string) => (
    <button
      className={"tab " + ((key === "run" ? onRuns : tab === key) ? "on" : "")}
      data-tab={key}
      onClick={() => setTab(key === "run" ? lastMode : key)}
    >
      {label}
    </button>
  );
  return (
    <header className="topbar">
      <div className="brand">
        <span className="dot" />
        SafeRoute <small>· АРМ оператора межцеховой логистики</small>
      </div>
      <nav className="tabs">
        {tabBtn("run", "Прогоны")}
        {tabBtn("launch", "Запуск")}
        {tabBtn("build", "Конструктор")}
      </nav>
      <span className="spacer" />
      <div className="seg" id="modeSeg" hidden={!onRuns}>
        <button className={tab === "run" ? "on" : ""} data-mode="run" onClick={() => setMode("run")}>
          Один прогон
        </button>
        <button className={tab === "cmp" ? "on" : ""} data-mode="cmp" onClick={() => setMode("cmp")}>
          Сравнение
        </button>
      </div>
      <button className="btn" id="expTrips" onClick={() => csv("trips")}>
        CSV рейсов
      </button>
      <button className="btn" id="expEv" onClick={() => csv("stops")}>
        CSV остановок
      </button>
    </header>
  );
}
