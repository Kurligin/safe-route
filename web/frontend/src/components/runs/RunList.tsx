import { useEffect, useRef } from "react";
import { runTitle, TIP } from "../../lib/labels";
import { app, selectRun, setShowLimits, useApp, visibleKeys } from "../../store/app";
import { Tip } from "../common/Tip";

/** Переключатель «Показать сценарии-ограничения» (прогоны витрины limits). */
export function LimitsToggle() {
  const on = useApp((s) => s.showLimits);
  const any = useApp((s) => Object.values(s.runs).some((R) => R.limit));
  if (!any) return null;
  return (
    <label className={"toggle " + (on ? "on" : "")} style={{ margin: "0 0 6px 2px", fontSize: 12 }}>
      <input type="checkbox" checked={on} onChange={(e) => setShowLimits(e.target.checked)} />
      <span className="sw" />
      Показать сценарии-ограничения
    </label>
  );
}

/** Список прогонов: основной подсвечен синим, второй в сравнении — оранжевым. */
export function RunList() {
  const order = useApp((s) => s.order);
  const runs = useApp((s) => s.runs);
  const list = useApp((s) => s.scenList);
  const primary = useApp((s) => s.primary);
  const compare = useApp((s) => s.compare);
  useApp((s) => s.showLimits);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    // выбранный прогон — в видимую часть панели, только по вертикали (узкие колонки не сдвигаются вбок)
    const on = ref.current?.querySelector<HTMLElement>(".run.on");
    const panel = on?.closest<HTMLElement>(".panel");
    if (!on || !panel) return;
    const r = on.getBoundingClientRect(),
      p = panel.getBoundingClientRect();
    if (r.bottom > p.bottom) panel.scrollTop += r.bottom - p.bottom;
    else if (r.top < p.top) panel.scrollTop -= p.top - r.top;
  }, [primary]);
  if (!order.length) return <div className="dim">Прогонов пока нет.</div>;
  const shown = visibleKeys(order, app.get()); // подписка на поля выше — через useApp
  return (
    <div className="run-list" ref={ref}>
      <LimitsToggle />
      {shown.map((k) => {
        const R = runs[k];
        const cls = k === primary ? "on" : k === compare ? "cmp" : "";
        return (
          <button
            key={k}
            className={"run " + cls}
            data-run={k}
            onClick={(e) => {
              if ((e.target as HTMLElement).classList.contains("tip")) return;
              selectRun(k);
            }}
          >
            <span className="nm">{runTitle(k, R.scenario, list)}</span>
            <span className={"sc " + (R.score.total < 50 ? "bad" : "")}>{R.score.total.toFixed(2)}</span>
            <span className="sub">
              {R.label} · seed {R.seed} <Tip text={TIP[R.label] || ""} />
            </span>
            <span className="sub id mono">{k}</span>
          </button>
        );
      })}
    </div>
  );
}
