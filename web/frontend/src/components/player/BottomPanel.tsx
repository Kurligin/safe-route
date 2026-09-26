import { app, tMax, useApp, useClock } from "../../store/app";
import { fmtT } from "../../lib/format";
import { isReady } from "../../lib/derive";
import { Tracks } from "./Tracks";
import { clock } from "../../store/app";

const SPEEDS = [1, 4, 16, 32];

/** Плеер (пуск, время, скорость, слежение) и шкала с графиками. */
export function BottomPanel() {
  const playing = useApp((s) => s.playing);
  const speed = useApp((s) => s.speed);
  const follow = useApp((s) => s.follow);
  const ready = useApp((s) => isReady(s.primary ? s.runs[s.primary] : null));
  useApp((s) => s.runs); // длительность меняется с подгрузкой прогонов
  const t = useClock();
  const toggle = () => {
    if (clock.get().t >= tMax()) clock.set({ t: 0 });
    app.set({ playing: !app.get().playing });
  };
  return (
    <section className="bottom">
      <div className="player">
        <button className="play" id="play" aria-label="Пуск" onClick={toggle}>
          {playing ? "❚❚" : "▶"}
        </button>
        <span className="time" id="time">
          {ready ? fmtT(t) + " / " + fmtT(tMax()) : "—"}
        </span>
        <div className="speeds">
          {SPEEDS.map((sp) => (
            <button key={sp} data-sp={sp} className={sp === speed ? "on" : ""} onClick={() => app.set({ speed: sp })}>
              ×{sp}
            </button>
          ))}
        </div>
        <label className="toggle" style={{ marginLeft: 8 }}>
          <input type="checkbox" id="follow" checked={follow} onChange={(e) => app.set({ follow: e.target.checked })} />
          <span className="sw" />
          Следовать за тележкой
        </label>
        <span className="hint">Пробел — пуск/пауза · ←/→ — ±1 с · Shift — ±10 с · клик по шкале — перемотка</span>
      </div>
      <Tracks />
    </section>
  );
}
