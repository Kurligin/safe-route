import type { Job, Meta, Run, Scenario, ScenItem, MapData, Group } from "./types";

/** Ошибка API: текст берётся из поля error ответа сервера. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, body?: unknown): Promise<T> {
  const init: RequestInit =
    body === undefined
      ? {}
      : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const r = await fetch("/api" + path, init);
  const d = (await r.json().catch(() => ({ error: "сервер вернул не JSON" }))) as T & { error?: string };
  if (!r.ok || d.error) throw new ApiError(r.status, d.error || "ошибка " + r.status);
  return d;
}

const enc = encodeURIComponent;

export const api = {
  meta: () => request<Meta>("/meta"),
  runs: () => request<Record<string, Run>>("/runs"),
  run: (key: string) => request<Run>("/runs/" + enc(key)),
  runLite: (key: string) => request<Run>("/runs/" + enc(key) + "?lite=1"),
  scenarios: () => request<{ items: ScenItem[]; baseMap: MapData | null }>("/scenarios"),
  scenario: (id: string) => request<{ id: string; group: Group; scenario: Scenario }>("/scenarios/" + enc(id)),
  scenarioRawUrl: (id: string) => "/api/scenarios/" + enc(id) + "?raw=1",
  saveScenario: (id: string | null, token: string | null, scenario: unknown) =>
    request<{ id: string; token: string }>("/scenarios", { id, token, scenario }),
  jobs: () => request<Job[]>("/jobs"),
  launch: (scenario: string, controllers: string[], seeds: number[]) =>
    request<{ jobs: string[] }>("/launch", { scenario, controllers, seeds }),
  tripsCsvUrl: (key: string) => "/api/runs/" + enc(key) + "/trips.csv",
  stopsCsvUrl: (key: string) => "/api/runs/" + enc(key) + "/stops.csv",
};
