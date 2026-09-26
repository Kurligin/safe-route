import { useEffect } from "react";
import { palette } from "../../lib/colors";
import { download } from "../../lib/download";
import { buildRu, CHECK_TIP, GROUPS, scenRu } from "../../lib/labels";
import { app, startBatch, setTab, useApp } from "../../store/app";
import { useStore } from "../../store/createStore";
import { Tip } from "../common/Tip";
import { MapLegend } from "../map/MapLegend";
import { MapView } from "../map/MapView";
import {
  B,
  builder,
  bump,
  checks,
  clickMap,
  curMap,
  curRoute,
  finishPed,
  makeCopy,
  openScenario,
  overlay,
  routes,
  saveCustom,
  scenarioBlob,
  startBuilder,
  TOOLS,
  type BState,
} from "./model";

const LOCK_ICON = (
  <svg viewBox="0 0 16 16">
    <rect x="3" y="7" width="10" height="7" rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
    <path d="M5.5 7V5a2.5 2.5 0 015 0v2" fill="none" stroke="currentColor" strokeWidth="1.5" />
  </svg>
);

/** Поле, которое применяется по «change» (потеря фокуса или Enter), как в АРМ. */
function CommitInput(props: {
  id: string;
  value: string | number;
  onCommit: (v: string) => void;
  disabled?: boolean;
  wide?: boolean;
}) {
  return (
    <input
      className={props.wide ? "sel" : "sel mono"}
      id={props.id}
      defaultValue={String(props.value)}
      disabled={props.disabled}
      style={props.wide ? { width: "100%" } : undefined}
      onBlur={(e) => e.target.value !== String(props.value) && props.onCommit(e.target.value)}
      onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
    />
  );
}

function Left({ v }: { v: number }) {
  const list = useApp((s) => s.scenList);
  const R = routes();
  const set = (p: Partial<BState>) => {
    Object.assign(B, p);
    bump();
  };
  const grp = list.find((s) => s.id === B.src.slice(3))?.group;
  const opt = (id: string) => (
    <option value={"sc:" + id} key={id}>
      {scenRu(id, list)}
    </option>
  );
  const customs = list.filter((s) => s.group === "Свои");
  const time = (id: string, k: "fog" | "gnss", i: 0 | 1) => (
    <CommitInput
      key={id + v}
      id={id}
      value={B[k][i]}
      onCommit={(val) => {
        B[k][i] = Math.max(0, +val || 0);
        bump();
      }}
    />
  );
  return (
    <aside className="panel bleft">
      <div className="sec">
        <h3>Открыть сценарий</h3>
        <select
          className="sel"
          id="bLib"
          style={{ width: "100%" }}
          value={B.src}
          onChange={(e) => openScenario(e.target.value)}
        >
          <option value="new">+ Новый сценарий</option>
          <optgroup label="Свои">
            {customs.length ? customs.map((c) => opt(c.id)) : <option disabled>пока нет</option>}
          </optgroup>
          {GROUPS.filter((g) => g !== "Свои").map((g) => {
            const ids = list.filter((s) => s.group === g).map((s) => s.id);
            return ids.length ? (
              <optgroup label={g} key={g}>
                {ids.map(opt)}
              </optgroup>
            ) : null;
          })}
        </select>
        {B.ro && (
          <>
            <div className="lock">
              {LOCK_ICON}Только просмотр — сценарий{" "}
              {grp === "Открытые" || grp === "Учебные" ? "организаторов" : "из набора проверки"} не меняется
            </div>
            <button className="btn" id="bCopy" style={{ width: "100%", marginTop: 8 }} onClick={makeCopy}>
              Создать копию и изменить
            </button>
          </>
        )}
      </div>
      <div className="sec">
        <h3>Название</h3>
        <CommitInput
          key={"n" + v}
          id="bName"
          value={B.name}
          wide
          disabled={B.ro}
          onCommit={(val) => set({ name: val.trim() || B.name })}
        />
      </div>
      <div className="sec">
        <h3>Маршрут</h3>
        <select
          className="sel"
          id="bRoute"
          style={{ width: "100%" }}
          disabled={B.ro}
          value={curRoute()}
          onChange={(e) => set({ route: e.target.value, missions: null, duration: null })}
        >
          {Object.entries(R).map(([k, r]) => (
            <option value={k} key={k}>
              {r.ru}
            </option>
          ))}
        </select>
      </div>
      <div className={B.ro ? "ro" : ""}>
        <div className="sec">
          <h3>Погода и связь</h3>
          <label className={"toggle " + (B.snow ? "on" : "")}>
            <input type="checkbox" id="bSnow" checked={B.snow} onChange={(e) => set({ snow: e.target.checked })} />
            <span className="sw" />
            Снег весь прогон
          </label>
          <div className="wrow">
            <label className={"toggle " + (B.fogOn ? "on" : "")}>
              <input type="checkbox" id="bFog" checked={B.fogOn} onChange={(e) => set({ fogOn: e.target.checked })} />
              <span className="sw" />
              Туман
            </label>
            {time("bF1", "fog", 0)}
            <span className="dim">–</span>
            {time("bF2", "fog", 1)}
            <span className="dim">с</span>
          </div>
          <div className="wrow">
            <label className={"toggle " + (B.gnssOn ? "on" : "")}>
              <input
                type="checkbox"
                id="bG"
                checked={B.gnssOn}
                onChange={(e) =>
                  set({ gnssOn: e.target.checked, gnss: e.target.checked && !B.gnss[1] ? [60, 110] : B.gnss })
                }
              />
              <span className="sw" />
              Нет спутника
            </label>
            {time("bG1", "gnss", 0)}
            <span className="dim">–</span>
            {time("bG2", "gnss", 1)}
            <span className="dim">с</span>
          </div>
        </div>
        <div className="sec">
          <h3>Добавить на карту</h3>
          <div className="tools">
            {TOOLS.map(([k, lbl, tip]) => (
              <button
                key={k}
                className={"toolb " + (B.tool === k ? "on" : "")}
                data-tool={k}
                onClick={(e) => {
                  if ((e.target as HTMLElement).classList.contains("tip")) return;
                  finishPed();
                  set({ tool: k });
                }}
              >
                <span className={"ic ic-" + k} />
                {lbl}
                <Tip text={tip} />
              </button>
            ))}
          </div>
          <div className="dim" style={{ fontSize: 12, marginTop: 8 }}>
            {B.tool.indexOf("ped") === 0 ? (
              B.cur ? (
                <>
                  Точек пути: {B.cur.pts.length}. Продолжайте кликать или{" "}
                  <button
                    className="btn small"
                    id="bPedDone"
                    onClick={() => {
                      finishPed();
                      bump();
                    }}
                  >
                    Готово
                  </button>
                </>
              ) : (
                "Кликните по карте, чтобы поставить первую точку пути."
              )
            ) : (
              "Кликните по карте."
            )}
          </div>
        </div>
      </div>
    </aside>
  );
}

function Right() {
  const meta = useApp((s) => s.meta);
  type Obj = [string, string, "peds" | "pallets" | "boxes" | "removed", number];
  const objs: Obj[] = [];
  B.peds.forEach((p, i) =>
    objs.push([
      `${p.inatt ? "Невнимательный пешеход" : "Пешеход"} ${i + 1}`,
      `${p.pts.length} точек · ${p.speed} м/с`,
      "peds",
      i,
    ]),
  );
  B.pallets.forEach((p, i) => objs.push([`Поддон ${i + 1}`, `появится на ${p.t} с`, "pallets", i]));
  B.boxes.forEach((_, i) => objs.push([`Препятствие ${i + 1}`, "нет на карте", "boxes", i]));
  B.removed.forEach((id, i) => objs.push([`Снесено: ${buildRu(id)}`, "есть на карте, нет в мире", "removed", i]));
  const run = async () => {
    let id: string;
    if (B.ro) id = B.src.slice(3);
    else {
      try {
        id = await saveCustom();
      } catch {
        return;
      }
    }
    const s = app.get();
    app.set({ launch: { ...s.launch, scen: [id], ctrl: s.meta.controllers.map((c) => c.key), seeds: "1" } });
    setTab("launch");
    await startBatch();
  };
  const save = async () => {
    try {
      const { blob, name } = await scenarioBlob();
      download(blob, name);
    } catch (e) {
      B.msg = ["bad", (e as Error).message];
    }
    bump();
  };
  return (
    <aside className="panel right bright">
      <div className="sec">
        <h3>Объекты сценария</h3>
        {objs.length ? (
          <div className="objs">
            {objs.map(([a, b, arr, i]) => (
              <div className="obj" key={arr + i}>
                <div>
                  <div>{a}</div>
                  <div className="dim" style={{ fontSize: 12 }}>
                    {b}
                  </div>
                </div>
                {!B.ro && (
                  <button
                    className="btn small"
                    data-del={arr + ":" + i}
                    onClick={() => {
                      (B[arr] as unknown[]).splice(i, 1);
                      bump();
                    }}
                  >
                    ✕
                  </button>
                )}
              </div>
            ))}
          </div>
        ) : (
          <div className="dim">Пока пусто. Выберите инструмент слева и кликните по карте.</div>
        )}
      </div>
      <div className="sec">
        <h3>
          <span>
            Проверка сценария <Tip text={CHECK_TIP} />
          </span>
        </h3>
        <div className="checks">
          {checks().map(([c, t], n) => (
            <div className={"ck " + c} key={n}>
              <span>{c === "warn" ? "!" : c === "ok" ? "✓" : "·"}</span>
              {t}
            </div>
          ))}
        </div>
      </div>
      <div className="sec">
        <button className="btn primary go" id="bRun" disabled={!meta.canRun || B.busy} onClick={run}>
          {B.busy ? "Сохраняю…" : "▶ Запустить: наш контроллер и Baseline"}
        </button>
        {!B.ro && (
          <button
            className="btn"
            id="bKeep"
            style={{ width: "100%", marginTop: 8 }}
            disabled={B.busy || !meta.canRun}
            title={meta.canRun ? "" : meta.reason}
            onClick={() => saveCustom().catch(() => {})}
          >
            Сохранить в «Свои»
          </button>
        )}
        <button className="btn" id="bSave" style={{ width: "100%", marginTop: 8 }} onClick={save}>
          Скачать сценарий (JSON)
        </button>
        {B.msg && (
          <div className={B.msg[0] === "bad" ? "lock" : "ck ok"} style={{ marginTop: 10 }}>
            {B.msg[0] !== "bad" && <span>✓</span>}
            {B.msg[1]}
          </div>
        )}
      </div>
    </aside>
  );
}

/** Вкладка «Конструктор»: библиотека и настройки слева, карта с инструментами, объекты и проверка справа. */
export function BuilderScreen() {
  const v = useStore(builder, (s) => s.v);
  useApp((s) => s.scenList);
  useEffect(() => startBuilder(), []);
  const C = palette();
  return (
    <div className="builder" style={{ gridRow: "2 / span 2", minHeight: 0 }}>
      <div className="bgrid">
        <Left v={v} />
        <MapView
          keys={[]}
          editor
          id="bview"
          getMap={curMap}
          overlay={(ctx, X, Y, sc) => overlay(ctx, X, Y, sc, C.bad, C.warn)}
          onClick={clickMap}
          redrawKey={v}
        >
          <div className="cap" id="bcap">
            {B.ro ? (
              <>
                <b>{B.name}</b> · только просмотр
              </>
            ) : (
              <>
                <b>Конструктор сценария</b> · выберите инструмент и кликайте по карте
              </>
            )}
          </div>
          <MapLegend kind="build" id="build" openByDefault={false} />
        </MapView>
        <Right />
      </div>
    </div>
  );
}
