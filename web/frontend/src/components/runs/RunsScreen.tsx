import { useEffect } from "react";
import { runTitle } from "../../lib/labels";
import { app, clock, readyRun, seek, tMax, useApp, type LayerKey } from "../../store/app";
import { MapLegend } from "../map/MapLegend";
import { MapView } from "../map/MapView";
import { BottomPanel } from "../player/BottomPanel";
import { ComparePrimary, CompareSecond, SinglePanel } from "./LeftPanels";
import { RightPanel } from "./RightPanel";

const LAYERS: [LayerKey, string][] = [
  ["zones", "Зоны"],
  ["path", "Маршрут рейса"],
  ["trail", "След (истина)"],
  ["est", "Оценка позы"],
  ["peds", "Пешеходы"],
  ["patches", "Расхождения карты"],
];

function Layers() {
  const layers = useApp((s) => s.layers);
  return (
    <div className="layers" id="layers">
      {LAYERS.map(([k, l]) => (
        <label key={k}>
          <input
            type="checkbox"
            data-layer={k}
            checked={layers[k]}
            onChange={(e) => app.set({ layers: { ...app.get().layers, [k]: e.target.checked } })}
          />
          {l}
        </label>
      ))}
    </div>
  );
}

function Caption({ which }: { which: 1 | 2 }) {
  const tab = useApp((s) => s.tab);
  const list = useApp((s) => s.scenList);
  const primary = useApp((s) => s.primary);
  const compare = useApp((s) => s.compare);
  useApp((s) => s.runs);
  const R = readyRun(primary),
    C = readyRun(compare);
  let body: React.ReactNode = null;
  if (R && tab === "cmp") {
    if (which === 1)
      body = (
        <>
          <b style={{ color: "var(--accent)" }}>● {R.label}</b> · seed {R.seed}
        </>
      );
    else
      body = C ? (
        <>
          <b style={{ color: "var(--cmp)" }}>● {C.label}</b> · seed {C.seed}
        </>
      ) : (
        <span>нет прогона для сравнения</span>
      );
  } else if (R && which === 1) {
    body = (
      <>
        <b>{runTitle(primary!, R.scenario, list)}</b> · {R.label} · seed {R.seed}
        {C && (
          <>
            {" "}
            &nbsp;<b style={{ color: "var(--cmp)" }}>● {C.label}</b>
          </>
        )}
      </>
    );
  }
  return (
    <div className="cap" id={"cap" + which}>
      {body}
    </div>
  );
}

/** Клавиши плеера: пробел, стрелки (Shift — по 10 с). */
function useKeys() {
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
      if (e.code === "Space") {
        e.preventDefault();
        if (!app.get().playing && clock.get().t >= tMax()) clock.set({ t: 0 });
        app.set({ playing: !app.get().playing });
      }
      if (e.code === "ArrowRight") seek(clock.get().t + (e.shiftKey ? 10 : 1), false);
      if (e.code === "ArrowLeft") seek(clock.get().t - (e.shiftKey ? 10 : 1), false);
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, []);
}

/** Вкладка «Прогоны»: «Один прогон» (3 колонки) или «Сравнение» (5 колонок), снизу — плеер и шкала. */
export function RunsScreen() {
  const tab = useApp((s) => s.tab);
  const primary = useApp((s) => s.primary);
  const compare = useApp((s) => s.compare);
  const cmp = tab === "cmp";
  useKeys();
  const keysMain = cmp ? [primary] : compare ? [primary, compare] : [primary];
  return (
    <>
      <div className={"main" + (cmp ? " cmp5" : "")}>
        {cmp ? <ComparePrimary /> : <SinglePanel />}
        {cmp && <CompareSecond />}
        <MapView keys={keysMain} id="v1" key={"m1" + tab}>
          <Caption which={1} />
          {!cmp && <Layers />}
          <MapLegend kind="run" id="main" openByDefault={false} />
        </MapView>
        {cmp && (
          <MapView keys={[compare]} key={"m2" + tab}>
            <Caption which={2} />
            <MapLegend kind="run" id="cmp" openByDefault={false} />
          </MapView>
        )}
        <RightPanel />
      </div>
      <BottomPanel />
    </>
  );
}
