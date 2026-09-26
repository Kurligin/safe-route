import { useEffect } from "react";
import { BuilderScreen } from "./components/builder/BuilderScreen";
import { TipLayer } from "./components/common/Tip";
import { LaunchScreen } from "./components/launch/LaunchScreen";
import { RunsScreen } from "./components/runs/RunsScreen";
import { TopBar } from "./components/TopBar";
import { app, clock, init, tMax, useApp } from "./store/app";

/** Цикл проигрывания: время идёт со скоростью ×speed, в конце — пауза. */
function usePlayback() {
  useEffect(() => {
    let prev = performance.now(),
      frame = 0;
    const loop = (now: number) => {
      const dt = (now - prev) / 1000;
      prev = now;
      const s = app.get();
      if (s.playing) {
        let t = clock.get().t + dt * s.speed;
        const end = tMax();
        if (t >= end) {
          t = end;
          app.set({ playing: false });
        }
        clock.set({ t });
      }
      frame = requestAnimationFrame(loop);
    };
    frame = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(frame);
  }, []);
}

export function App() {
  const status = useApp((s) => s.status);
  const loadError = useApp((s) => s.loadError);
  const tab = useApp((s) => s.tab);
  useEffect(() => {
    void init();
  }, []);
  usePlayback();
  return (
    <>
      <TopBar />
      {status === "loading" && (
        <div style={{ padding: 18, gridRow: "2 / span 2" }} className="dim">
          Загрузка…
        </div>
      )}
      {status === "error" && (
        <div style={{ padding: 18, gridRow: "2 / span 2" }}>
          <div className="lock">Сервер не ответил: {loadError}</div>
        </div>
      )}
      {status === "ready" && (tab === "run" || tab === "cmp") && <RunsScreen />}
      {status === "ready" && tab === "launch" && <LaunchScreen />}
      {status === "ready" && tab === "build" && <BuilderScreen />}
      <TipLayer />
    </>
  );
}
