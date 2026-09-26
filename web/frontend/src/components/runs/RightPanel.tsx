import { fmtT } from "../../lib/format";
import { derived, readyRun, useApp } from "../../store/app";
import { useStableT, useThrottledT } from "../../store/useClockView";
import { NowRows } from "./NowRows";
import { EventsTable, TripsTable } from "./Tables";

const note = { textTransform: "none", letterSpacing: 0 } as const;

function Now({ keys }: { keys: (string | null)[] }) {
  const t = useThrottledT(120);
  const runs = keys.map((k) => readyRun(k)).filter((R): R is NonNullable<typeof R> => !!R);
  return (
    <div className="sec">
      <h3>Сейчас · {fmtT(t)}</h3>
      <div id="now">
        <NowRows runs={runs} t={t} />
      </div>
    </div>
  );
}

/** Правая колонка: «Сейчас», журнал рейсов, остановки и штрафы (в сравнении — по обоим прогонам). */
export function RightPanel() {
  const primary = useApp((s) => s.primary);
  const compare = useApp((s) => s.compare);
  const tab = useApp((s) => s.tab);
  useApp((s) => s.runs);
  const t = useStableT();
  const A = readyRun(primary);
  if (!A) return <aside className="panel right" />;
  const B = readyRun(compare);
  if (tab === "cmp" && B) {
    return (
      <aside className="panel right">
        <Now keys={[primary, compare]} />
        <div className="sec">
          <h3>
            <span style={{ color: "var(--accent)" }}>● Журнал рейсов · {A.label}</span>
            <span className="dim" style={note}>
              можно выбрать
            </span>
          </h3>
          <TripsTable d={derived(A)} t={t} />
        </div>
        <div className="sec">
          <h3>
            <span style={{ color: "var(--cmp)" }}>● Журнал рейсов · {B.label}</span>
          </h3>
          <TripsTable d={derived(B)} t={t} />
        </div>
        <div className="sec">
          <h3>
            <span style={{ color: "var(--accent)" }}>● Остановки и штрафы</span>
            <span className="dim" style={note}>
              можно выбрать
            </span>
          </h3>
          <EventsTable d={derived(A)} t={t} />
        </div>
        <div className="sec">
          <h3>
            <span style={{ color: "var(--cmp)" }}>● Остановки и штрафы</span>
          </h3>
          <EventsTable d={derived(B)} t={t} />
        </div>
      </aside>
    );
  }
  const keys = tab === "cmp" ? [primary] : compare ? [primary, compare] : [primary];
  return (
    <aside className="panel right">
      <Now keys={keys} />
      <div className="sec">
        <h3>
          Журнал рейсов{" "}
          <span className="dim" style={note}>
            можно выбрать
          </span>
        </h3>
        <div id="trips">
          <TripsTable d={derived(A)} t={t} />
        </div>
      </div>
      <div className="sec">
        <h3>
          Остановки и штрафы{" "}
          <span className="dim" style={note}>
            можно выбрать
          </span>
        </h3>
        <div id="evs">
          <EventsTable d={derived(A)} t={t} />
        </div>
      </div>
    </aside>
  );
}
