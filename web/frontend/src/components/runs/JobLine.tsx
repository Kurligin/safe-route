import { useApp } from "../../store/app";

/** Полоска и строка хода одиночного запуска из панели прогона. */
export function JobLine({ role, idle }: { role: "primary" | "compare"; idle?: string }) {
  const oj = useApp((s) => (s.openJob && s.openJob.role === role ? s.openJob : null));
  const j = useApp((s) => (oj && oj.id ? s.jobs[oj.id] : undefined));
  let width = 0;
  let msg: React.ReactNode = idle || "";
  if (oj && oj.error) msg = <span className="bad">{oj.error}</span>;
  else if (j) {
    width = j.state === "queued" ? 3 : j.p || 0;
    if (j.state === "queued") msg = "в очереди…";
    else if (j.state === "run") msg = "прогон… " + Math.round(j.p || 0) + "% · " + j.scenario + ", seed " + j.seed;
    else if (j.state === "error") msg = <span className="bad">ошибка: {j.error || ""}</span>;
    else msg = "готово · " + j.scenario + " · " + (j.total || 0).toFixed(2);
  }
  return (
    <>
      <div className="progress" style={{ margin: "8px 0 0" }}>
        <i style={{ width: width + "%" }} />
      </div>
      <div className="dim mono" style={{ fontSize: 11 }} title={j?.cmd || ""}>
        {msg}
      </div>
    </>
  );
}
