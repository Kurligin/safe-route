import { plural, scoreCls } from "../../lib/format";
import { GROUPS, runTitle, SCEN_TIP, SCORE_TIP, SEED_TIP, scenRu, TIP } from "../../lib/labels";
import { app, clock, openFromLaunch, parseSeeds, setTab, startBatch, useApp, visibleKeys } from "../../store/app";
import { LimitsToggle } from "../runs/RunList";
import { Tip } from "../common/Tip";

const toggleIn = (arr: string[], id: string) => (arr.includes(id) ? arr.filter((x) => x !== id) : [...arr, id]);

function Form() {
  const L = useApp((s) => s.launch);
  const list = useApp((s) => s.scenList);
  const meta = useApp((s) => s.meta);
  // обработчики читают свежее состояние: несколько быстрых кликов подряд не теряют друг друга
  const setL = (fn: (cur: typeof L) => Partial<typeof L>) => {
    const cur = app.get().launch;
    if (!cur.running) app.set({ launch: { ...cur, ...fn(cur) } });
  };
  const ns = parseSeeds(L.seeds).length;
  const n = L.scen.length * L.ctrl.length * ns;
  const mins = Math.max(1, Math.round((n * (meta.avgS || 6)) / (meta.parallel || 2) / 60));
  const groups = GROUPS.map((g) => [g, list.filter((s) => s.group === g).map((s) => s.id)] as const).filter(
    ([, ids]) => ids.length,
  );
  const note = !meta.canRun ? meta.reason || "Запуск прогонов недоступен" : L.error;
  return (
    <div className="form">
      <h2>Запуск прогонов</h2>
      <div className="field">
        <span>Сценарии</span>
        {groups.map(([g, ids]) => (
          <div className="grp" key={g}>
            <span className="gl">
              {g} <Tip text={SCEN_TIP[g] || ""} />
            </span>
            <div className="chips">
              {ids.map((id) => (
                <button
                  key={id}
                  className={"chip " + (L.scen.includes(id) ? "on" : "")}
                  data-scen={id}
                  onClick={() => setL((c) => ({ scen: toggleIn(c.scen, id) }))}
                >
                  {scenRu(id, list)}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
      <div className="field">
        <span>Контроллеры</span>
        <div className="chips">
          {meta.controllers.map((c) => (
            <button
              key={c.key}
              className={"chip " + (L.ctrl.includes(c.key) ? "on" : "")}
              data-ctrl={c.key}
              onClick={(e) => {
                if ((e.target as HTMLElement).classList.contains("tip")) return;
                setL((cur) => ({ ctrl: toggleIn(cur.ctrl, c.key) }));
              }}
            >
              <span>{c.label}</span>
              <Tip text={TIP[c.label] || ""} />
            </button>
          ))}
        </div>
      </div>
      <div className="field">
        <span>
          Seed <Tip text={SEED_TIP} />
        </span>
        <input
          className="sel mono"
          id="lSeeds"
          value={L.seeds}
          onChange={(e) => app.set({ launch: { ...app.get().launch, seeds: e.target.value } })}
        />
      </div>
      <div className="summary">
        {L.scen.length} {plural(L.scen.length, "сценарий", "сценария", "сценариев")} × {L.ctrl.length}{" "}
        {plural(L.ctrl.length, "контроллер", "контроллера", "контроллеров")} × {ns} seed ={" "}
        <b>
          {n} {plural(n, "прогон", "прогона", "прогонов")}
        </b>{" "}
        · около {mins} мин
      </div>
      <button
        className="btn primary go"
        id="lGo"
        disabled={!n || L.running || !meta.canRun}
        onClick={() => startBatch()}
      >
        {L.running ? "Выполняется…" : `▶ Запустить ${n} ${plural(n, "прогон", "прогона", "прогонов")}`}
      </button>
      {note && (
        <div className="lock" style={{ marginTop: 10 }}>
          {note}
        </div>
      )}
      <div className="field" style={{ marginTop: 14 }}>
        <span>Команда для каждого прогона</span>
        <div className="cmdline">
          python -m amrsim run scenarios/&lt;сценарий&gt;.json --controller &lt;контроллер&gt;/controller.py --seed
          &lt;seed&gt; --report runs/&lt;id&gt;.json --log runs/&lt;id&gt;.jsonl
        </div>
      </div>
    </div>
  );
}

function Queue() {
  const L = useApp((s) => s.launch);
  const all = useApp((s) => s.jobs);
  const runs = useApp((s) => s.runs);
  const list = useApp((s) => s.scenList);
  const meta = useApp((s) => s.meta);
  const lastMode = useApp((s) => s.lastMode);
  const jobs = L.jobIds.map((id) => all[id]).filter(Boolean);
  const n = jobs.length,
    done = jobs.filter((j) => j.state === "done" || j.state === "error").length;
  const run = jobs.filter((j) => j.state === "run");
  const bar = n ? (100 * (done + run.reduce((a, j) => a + (j.p || 0) / 100, 0))) / n : 0;
  const left =
    (jobs.filter((j) => j.state === "queued").length * (meta.avgS || 6)) / (meta.parallel || 2) +
    run.reduce((a, j) => Math.max(a, j.left || 0), 0);
  const errs = jobs.filter((j) => j.state === "error").length;
  const goRuns = () => {
    const first = jobs.find((j) => j.state === "done" && j.key && runs[j.key]);
    const s: { primary?: string; compare?: string | null } = {};
    if (first && first.key) s.primary = first.key;
    const pair =
      first &&
      jobs.find(
        (j) => j.state === "done" && j.key !== first.key && j.scenario === first.scenario && j.seed === first.seed,
      );
    s.compare = pair && lastMode === "cmp" ? pair.key || null : app.get().compare;
    app.set(s);
    clock.set({ t: 0 });
    setTab(lastMode);
  };
  return (
    <>
      <div className="qhead">
        <h3>Очередь</h3>
        <span id="qStat" className="dim">
          {n > 0 && L.running && `выполнено ${done} из ${n} · осталось ~${Math.max(1, Math.round(left))} с`}
          {n > 0 && L.finished && (
            <>
              готово{errs ? ` · ошибок: ${errs}` : ""} · прогоны добавлены во вкладку «Прогоны»{" "}
              <button className="btn small" id="toRuns" onClick={goRuns}>
                Перейти
              </button>
            </>
          )}
        </span>
      </div>
      <div className="progress big">
        <i id="qBar" style={{ width: bar + "%" }} />
      </div>
      <div id="queue">
        {!n ? (
          <div className="empty">
            Выберите сценарии, контроллеры и seed слева и нажмите «Запустить». Прогоны пойдут по {meta.parallel || 2}{" "}
            одновременно, у каждого своя строка с ходом выполнения.
          </div>
        ) : (
          <table className="list q">
            <tbody>
              <tr>
                <th>Сценарий</th>
                <th>Контроллер</th>
                <th>Seed</th>
                <th style={{ width: "34%" }}>Ход</th>
                <th>Итог</th>
              </tr>
              {jobs.map((j) => (
                <tr key={j.id}>
                  <td>
                    {scenRu(j.scenario, list)}
                    <div className="sub id mono">{j.scenario}</div>
                  </td>
                  <td>{j.label || ""}</td>
                  <td className="mono">{j.seed}</td>
                  <td>
                    <div className={"progress row " + (j.state === "run" ? "live" : "")}>
                      <i
                        style={{
                          width: (j.p || 0) + "%",
                          ...(j.state === "error" ? { background: "var(--bad)" } : {}),
                        }}
                      />
                    </div>
                  </td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    {j.state === "queued" ? (
                      <span className="dim">в очереди</span>
                    ) : j.state === "run" ? (
                      <span className="warn">идёт…</span>
                    ) : j.state === "error" ? (
                      <>
                        <span className="bad">ошибка</span> <Tip text={j.error || ""} />
                      </>
                    ) : (
                      <span className={"mono " + scoreCls(j.total || 0)}>{(j.total || 0).toFixed(2)}</span>
                    )}
                    {j.state === "done" && j.key && runs[j.key] && (
                      <>
                        {" "}
                        <button className="btn small" data-open={j.key} onClick={() => openFromLaunch(j.key!, "run")}>
                          Открыть
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

function History() {
  const runs = useApp((s) => s.runs);
  const list = useApp((s) => s.scenList);
  useApp((s) => s.showLimits);
  const keys = visibleKeys(Object.keys(runs), app.get()).sort(
    (a, b) => (runs[b].mtime || 0) - (runs[a].mtime || 0) || a.localeCompare(b),
  );
  if (!keys.length) return <div className="empty">Прогонов пока нет.</div>;
  return (
    <table className="list">
      <tbody>
        <tr>
          <th>Сценарий</th>
          <th>Контроллер</th>
          <th>Seed</th>
          <th>
            Итог <Tip text={SCORE_TIP} />
          </th>
          <th>Доставлено</th>
          <th>Шаг, мс</th>
          <th />
        </tr>
        {keys.map((k) => {
          const R = runs[k];
          return (
            <tr key={k}>
              <td>
                {runTitle(k, R.scenario, list)}
                <div className="sub id mono">{k}</div>
              </td>
              <td>{R.label}</td>
              <td className="mono">{R.seed}</td>
              <td className={"mono " + scoreCls(R.score.total)}>{R.score.total.toFixed(2)}</td>
              <td className="mono">
                {R.score.deliveries}/{R.missions.length}
              </td>
              <td className="mono">{(R.step_ms.mean || 0).toFixed(2)}</td>
              <td style={{ whiteSpace: "nowrap" }}>
                <button className="btn small" data-open={k} onClick={() => openFromLaunch(k, "run")}>
                  Открыть
                </button>{" "}
                <button className="btn small" data-cmpopen={k} onClick={() => openFromLaunch(k, "cmp")}>
                  Сравнить
                </button>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/** Вкладка «Запуск»: форма слева, очередь с ходом прогонов и история справа. */
export function LaunchScreen() {
  return (
    <div style={{ gridRow: "2 / span 2", minHeight: 0 }}>
      <div className="launch">
        <Form />
        <div className="out">
          <Queue />
          <h3 style={{ marginTop: 22 }}>История прогонов</h3>
          <LimitsToggle />
          <div id="hist">
            <History />
          </div>
        </div>
      </div>
    </div>
  );
}
