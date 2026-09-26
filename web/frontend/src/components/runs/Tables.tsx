import type { Derived } from "../../lib/derive";
import { fmtT } from "../../lib/format";
import { EP_RU, ptRu, REASON_RU } from "../../lib/labels";
import { seek } from "../../store/app";

/** Журнал рейсов: клик — перемотка к началу рейса. */
export function TripsTable({ d, t }: { d: Derived; t: number }) {
  return (
    <>
      <table className="list">
        <tbody>
          <tr>
            <th>Рейс</th>
            <th>Маршрут</th>
            <th>Время</th>
            <th>Итог</th>
          </tr>
          {d.trips.map((m) => {
            const dur = (m.t_arrival != null ? m.t_arrival : m.t_end) - m.t_start;
            const cur = t >= m.t_start && t < m.t_end ? "cur" : "";
            return (
              <tr key={m.id} className={"click " + cur} onClick={() => seek(m.t_start, false)}>
                <td className="mono">{m.id}</td>
                <td>
                  {ptRu(m.from)} → {ptRu(m.to)}
                </td>
                <td className="mono">
                  {dur.toFixed(1)} / {m.deadline_s.toFixed(0)} с
                </td>
                <td className={m.delivered ? "ok" : "bad"}>{REASON_RU[m.reason] || m.reason}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {!d.trips.length && (
        <div className="dim" style={{ marginTop: 8, fontSize: 12 }}>
          Рейсов в логе нет.
        </div>
      )}
    </>
  );
}

/** Остановки и штрафы: клик — перемотка за 2 с до события с паузой. */
export function EventsTable({ d, t }: { d: Derived; t: number }) {
  const items = [
    ...d.episodes.map((e) => ({
      t: e.t_start,
      dur: e.t_end - e.t_start,
      kind: "штраф",
      txt: (EP_RU[e.type] || e.type) + " · " + (e.cost ? e.cost.toFixed(1) : "0") + " б.",
      cls: "bad",
    })),
    ...d.stops.map((s) => ({
      t: s.t0,
      dur: s.t1 - s.t0,
      kind: s.full ? "стоп" : "медленно",
      txt: s.reason,
      cls: s.full ? "warn" : "dim",
    })),
  ].sort((a, b) => a.t - b.t);
  return (
    <>
      <table className="list">
        <tbody>
          <tr>
            <th>t</th>
            <th>Длит.</th>
            <th>Что</th>
            <th>Причина</th>
          </tr>
          {items.map((it, n) => (
            <tr
              key={n}
              className={"click " + (t >= it.t && t <= it.t + it.dur ? "cur" : "")}
              onClick={() => seek(Math.max(0, it.t - 2), true)}
            >
              <td className="mono">{fmtT(it.t)}</td>
              <td className="mono">{it.dur.toFixed(1)} с</td>
              <td className={it.cls}>{it.kind}</td>
              <td>{it.txt}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {!d.episodes.length && (
        <div className="dim" style={{ marginTop: 8, fontSize: 12 }}>
          Штрафных эпизодов в этом прогоне нет.
        </div>
      )}
    </>
  );
}
