import type { ReactNode } from "react";
import type { ReadyRun } from "../../api/types";
import { idxAt } from "../../lib/derive";
import { f2 } from "../../lib/format";
import { noteRu, ptRu, ST_RU } from "../../lib/labels";

const Status = ({ st }: { st: string }) => <span className={"status " + st}>{ST_RU[st] || st}</span>;
const ecls = (e: number | null) => (e == null ? "" : e > 1 ? "bad" : e > 0.5 ? "warn" : "");
const hcls = (x: number | null) => (x != null && x < 3 ? "warn" : "");

/** «Сейчас»: статус, причина, рейс, скорость, ошибка позы, зазор; при сравнении — две колонки. */
export function NowRows({ runs, t }: { runs: ReadyRun[]; t: number }) {
  if (!runs.length) return <div className="dim">—</div>;
  const R = runs[0],
    i = idxAt(R, t),
    T = R.ticks;
  const C2 = runs[1] || null,
    j = C2 ? idxAt(C2, t) : 0,
    T2 = C2 ? C2.ticks : null;
  const two = !!T2;
  const mid = T.m[i];
  const mh = R.missions_hdr.find((m) => m.id === mid);
  const nt = noteRu(T.nt[i]);
  const rows: ReactNode[] = [];
  const row = (k: string, v1: ReactNode, v2: ReactNode, cls1 = "", cls2 = "") =>
    rows.push(
      <div className="r" key={k}>
        <span className="k">{k}</span>
        <span className={"v " + cls1}>{v1}</span>
        {two && <span className={"v c " + cls2}>{v2}</span>}
      </div>,
    );
  if (two)
    rows.push(
      <div className="r hd" key="hd">
        <span className="k" />
        <span className="v" style={{ color: "var(--accent)" }}>
          ● {R.label}
        </span>
        <span className="v c">● {C2.label}</span>
      </div>,
    );
  row("Статус", <Status st={T.st[i]} />, two ? <Status st={T2.st[j]} /> : "");
  const nt2 = two ? noteRu(T2.nt[j]) : "";
  row("Причина", nt || "—", nt2 || "—", nt ? "warn" : "dim", nt2 ? "warn" : "dim");
  rows.push(
    <div className="r" key="trip">
      <span className="k">Рейс</span>
      <span className="v" style={{ gridColumn: "2 / -1" }}>
        {mh ? `${mh.id} · ${ptRu(mh.from)} → ${ptRu(mh.to)}` : "—"}
      </span>
    </div>,
  );
  row("Скорость", f2(Math.abs(T.v[i])) + " м/с", two ? f2(Math.abs(T2.v[j])) + " м/с" : "");
  row("Ошибка позы", f2(T.err[i]) + " м", two ? f2(T2.err[j]) + " м" : "", ecls(T.err[i]), two ? ecls(T2.err[j]) : "");
  const hum = T.hum[i];
  row(
    "Зазор до человека",
    hum == null ? "—" : f2(hum) + " м",
    two ? (T2.hum[j] == null ? "—" : f2(T2.hum[j]) + " м") : "",
    hcls(hum),
    two ? hcls(T2.hum[j]) : "",
  );
  return <div className={"rows " + (two ? "two" : "")}>{rows}</div>;
}
