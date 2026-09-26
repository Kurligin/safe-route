/** Время прогона «м:сс.с». */
export const fmtT = (t: number): string => {
  t = Math.max(0, t);
  const m = Math.floor(t / 60),
    s = t - m * 60;
  return m + ":" + (s < 10 ? "0" : "") + s.toFixed(1);
};
export const f2 = (v: number | null | undefined): string => (v == null ? "—" : v.toFixed(2));
export const plural = (n: number, a: string, b: string, c: string): string =>
  n % 10 === 1 && n % 100 !== 11 ? a : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20) ? b : c;
export const scoreCls = (v: number): string => (v < 50 ? "bad" : v < 90 ? "warn" : "ok");
