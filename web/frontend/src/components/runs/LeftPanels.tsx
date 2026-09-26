import { useState } from "react";
import type { ReadyRun } from "../../api/types";
import { sameScen } from "../../lib/derive";
import { fmtT } from "../../lib/format";
import { SCORE_TIP, runTitle, TIP } from "../../lib/labels";
import { app, derived, readyRun, runOne, selectCompare, setTab, useApp, visibleKeys } from "../../store/app";
import { Tip } from "../common/Tip";
import { JobLine } from "./JobLine";
import { BLK, blockVal, ScoreBlock } from "./ScoreBlock";
import { RunList } from "./RunList";

const plain = { textTransform: "none", letterSpacing: 0 } as const;

function PanelError() {
  const err = useApp((s) => s.panelError);
  return err ? (
    <div className="lock" style={{ margin: 10 }}>
      {err}
    </div>
  ) : null;
}

/** Пустая панель: прогонов нет или прогон ещё грузится. */
function Empty({ loadingRun }: { loadingRun: boolean }) {
  return (
    <div className="sec">
      <h3>Прогон</h3>
      <div className="empty">
        {loadingRun
          ? "Загрузка прогона…"
          : "Прогонов пока нет. Запустите сценарий во вкладке «Запуск» — результат появится здесь."}
      </div>
      {!loadingRun && (
        <button className="btn primary" style={{ width: "100%", marginTop: 10 }} onClick={() => setTab("launch")}>
          Перейти к запуску
        </button>
      )}
    </div>
  );
}

function Reseed({ R }: { R: ReadyRun }) {
  const meta = useApp((s) => s.meta);
  const known = useApp((s) => s.scenList.some((q) => q.id === R.scenario));
  const [seed, setSeed] = useState(String(R.seed + 1));
  const [forSeed, setForSeed] = useState(R.seed);
  if (forSeed !== R.seed) {
    setForSeed(R.seed);
    setSeed(String(R.seed + 1));
  }
  return (
    <>
      <div className="reseed">
        <span className="dim">Прогнать заново с seed</span>
        <input className="sel mono" id="reSeed" value={seed} onChange={(e) => setSeed(e.target.value)} />
        <button
          className="btn small"
          id="reGo"
          disabled={!(meta.canRun && known)}
          onClick={() => {
            const n = parseInt(seed, 10);
            if (n >= 0) void runOne(R.scenario, R.ctrl, n, "primary");
          }}
        >
          Запустить
        </button>
      </div>
      <JobLine role="primary" idle={meta.canRun ? "" : meta.reason} />
    </>
  );
}

/** Левая колонка режима «Один прогон». */
export function SinglePanel() {
  const primary = useApp((s) => s.primary);
  const compare = useApp((s) => s.compare);
  const list = useApp((s) => s.scenList);
  const runs = useApp((s) => s.runs);
  const R = readyRun(primary);
  if (!R)
    return (
      <aside className="panel">
        <PanelError />
        <Empty loadingRun={!!(primary && runs[primary])} />
      </aside>
    );
  const cmp = readyRun(compare);
  return (
    <aside className="panel">
      <PanelError />
      <div className="sec">
        <h3>Прогон</h3>
        <div className="kv">
          <dt>Сценарий</dt>
          <dd>{runTitle(primary!, R.scenario, list)}</dd>
          <dt>Контроллер</dt>
          <dd>
            {R.label} <Tip text={TIP[R.label] || ""} />
          </dd>
          <dt>Seed</dt>
          <dd className="mono">{R.seed}</dd>
          <dt>Длительность</dt>
          <dd className="mono">{fmtT(derived(R).tEnd)}</dd>
          <dt>Шаг контроллера</dt>
          <dd className="mono">{(R.step_ms.mean || 0).toFixed(2)} мс</dd>
        </div>
        <Reseed R={R} />
      </div>
      <div className="sec">
        <h3>
          <span>
            Счёт сценария <Tip text={SCORE_TIP} />
          </span>
          {cmp && <span style={{ color: "var(--cmp)", ...plain }}>vs {cmp.label}</span>}
        </h3>
        <ScoreBlock s={R.score} c={cmp ? cmp.score : null} />
      </div>
      <div className="sec">
        <h3>Прогоны</h3>
        <RunList />
      </div>
    </aside>
  );
}

function Card({ k, R, col, extra }: { k: string; R: ReadyRun; col: string; extra?: React.ReactNode }) {
  const list = useApp((s) => s.scenList);
  return (
    <>
      <div className="sec colhead" style={{ ["--c" as string]: col }}>
        <h3>
          <span style={{ color: col }}>
            ● {R.label} <Tip text={TIP[R.label] || ""} />
          </span>
        </h3>
        <div className="kv">
          <dt>Сценарий</dt>
          <dd>{runTitle(k, R.scenario, list)}</dd>
          <dt>Seed</dt>
          <dd className="mono">{R.seed}</dd>
          <dt>Длительность</dt>
          <dd className="mono">{fmtT(derived(R).tEnd)}</dd>
          <dt>Шаг</dt>
          <dd className="mono">{(R.step_ms.mean || 0).toFixed(2)} мс</dd>
        </div>
      </div>
      <div className="sec">
        <h3>
          <span>
            Счёт сценария <Tip text={SCORE_TIP} />
          </span>
        </h3>
        <ScoreBlock s={R.score} />
      </div>
      {extra}
    </>
  );
}

/** Первая колонка сравнения: основной прогон и список. */
export function ComparePrimary() {
  const primary = useApp((s) => s.primary);
  const runs = useApp((s) => s.runs);
  const R = readyRun(primary);
  if (!R)
    return (
      <aside className="panel">
        <PanelError />
        <Empty loadingRun={!!(primary && runs[primary])} />
      </aside>
    );
  return (
    <aside className="panel">
      <PanelError />
      <Card
        k={primary!}
        R={R}
        col="var(--accent)"
        extra={
          <div className="sec">
            <h3>Пара прогонов</h3>
            <RunList />
          </div>
        }
      />
    </aside>
  );
}

/** Вторая колонка сравнения: выбор пары, её счёт и выигрыш по блокам; без пары — запуск второго контроллера. */
export function CompareSecond() {
  const primary = useApp((s) => s.primary);
  const compare = useApp((s) => s.compare);
  const order = useApp((s) => s.order);
  const runs = useApp((s) => s.runs);
  const meta = useApp((s) => s.meta);
  const R = readyRun(primary);
  if (!R) return <aside className="panel" />;
  const cmp = readyRun(compare);
  useApp((s) => s.showLimits);
  const others = visibleKeys(sameScen(primary!, order, runs), app.get());
  const short = (k: string) => runs[k].label + " · seed " + runs[k].seed;
  const optLabel = (k: string) =>
    others.some((o) => o !== k && short(o) === short(k)) ? short(k) + " · " + k : short(k);
  if (!cmp) {
    const other = meta.controllers.find((c) => c.key !== R.ctrl) || meta.controllers[0];
    return (
      <aside className="panel">
        <div className="sec">
          <h3>Сравнить с</h3>
          <div className="empty">
            Другого прогона этого сценария пока нет. Запустите второй контроллер на том же seed — он появится здесь.
          </div>
          <div className="reseed" style={{ gridTemplateColumns: "1fr auto" }}>
            <span className="dim">
              {other ? other.label : ""} · seed {R.seed}
            </span>
            <button
              className="btn small"
              id="pairGo"
              disabled={!(meta.canRun && other)}
              onClick={() => other && runOne(R.scenario, other.key, R.seed, "compare")}
            >
              Запустить
            </button>
          </div>
          <JobLine role="compare" />
        </div>
      </aside>
    );
  }
  const dt = R.score.total - cmp.score.total;
  return (
    <aside className="panel">
      <div className="sec">
        <h3>Сравнить с</h3>
        <select
          className="sel"
          id="cmpSel"
          style={{ width: "100%" }}
          value={compare || ""}
          onChange={(e) => selectCompare(e.target.value)}
        >
          {others.map((k) => (
            <option value={k} key={k}>
              {optLabel(k)}
            </option>
          ))}
        </select>
      </div>
      <Card
        k={compare!}
        R={cmp}
        col="var(--cmp)"
        extra={
          <div className="sec">
            <h3>Выигрыш по блокам</h3>
            <div className="dim" style={{ fontSize: 12, margin: "-4px 0 8px" }}>
              {R.label} относительно «{cmp.label}»
            </div>
            <table className="list">
              <tbody>
                {BLK.map(([k, l]) => {
                  const dv = blockVal(R.score, k) - blockVal(cmp.score, k);
                  return (
                    <tr key={k}>
                      <td>{l}</td>
                      <td
                        className={"mono " + (dv > 0.005 ? "ok" : dv < -0.005 ? "bad" : "dim")}
                        style={{ textAlign: "right" }}
                      >
                        {dv > 0 ? "+" : ""}
                        {dv.toFixed(2)}
                      </td>
                    </tr>
                  );
                })}
                <tr>
                  <td>
                    <b>Итог сценария</b>
                  </td>
                  <td className="mono" style={{ textAlign: "right" }}>
                    <b>{(dt > 0 ? "+" : "") + dt.toFixed(2)}</b>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        }
      />
    </aside>
  );
}
