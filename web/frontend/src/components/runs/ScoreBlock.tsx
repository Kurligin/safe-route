import type { BlockKey, Score } from "../../api/types";

export const BLK: [BlockKey, string][] = [
  ["delivery", "Доставка"],
  ["efficiency", "Эффективность"],
  ["safety", "Безопасность"],
  ["rules", "Правила"],
  ["pose", "Честность позы"],
  ["collisions", "Столкновения"],
];
export const blockVal = (s: Score, k: BlockKey): number => s.blocks[k] ?? 0;

/** Счёт сценария: итог и полосы блоков; при сравнении — вторая полоса и итог второго прогона. */
export function ScoreBlock({ s, c }: { s: Score; c?: Score | null }) {
  return (
    <>
      <div className="score-big">
        <span className="n">{s.total.toFixed(2)}</span>
        <span className="of">/ 100</span>
        {c && <span className="cmp">{c.total.toFixed(2)}</span>}
      </div>
      <div className="blocks">
        {BLK.map(([k, lbl]) => {
          const mx = s.max[k] || 1,
            v = blockVal(s, k);
          const w = k === "collisions" ? (v < 0 ? 100 : 0) : (Math.max(0, v) / mx) * 100;
          const cv = c ? blockVal(c, k) : 0;
          const wc = c ? (k === "collisions" ? (cv < 0 ? 100 : 0) : (Math.max(0, cv) / mx) * 100) : 0;
          const badv = k === "collisions" ? v < 0 : v < mx - 0.01;
          return (
            <div className={"blk " + (badv ? "bad" : "")} key={k}>
              <span className="lbl">{lbl}</span>
              <span className="bar">
                <i style={{ width: w + "%", ...(k === "collisions" ? { background: "var(--bad)" } : {}) }} />
                {c && <i className="c" style={{ width: wc + "%" }} />}
              </span>
              <span className="val">{v.toFixed(1)}</span>
            </div>
          );
        })}
      </div>
    </>
  );
}
