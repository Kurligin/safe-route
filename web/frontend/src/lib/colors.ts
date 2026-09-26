/** Цвета из CSS-токенов (arm.css) для рисования на canvas. Читаются один раз после загрузки стилей. */
export interface Palette {
  accent: string;
  cmp: string;
  ok: string;
  warn: string;
  bad: string;
  fg: string;
  fg2: string;
  fg3: string;
  line: string;
  view: string;
}

let cache: Palette | null = null;

export function palette(): Palette {
  if (cache) return cache;
  const s = getComputedStyle(document.documentElement);
  const v = (n: string) => s.getPropertyValue(n).trim();
  cache = {
    accent: v("--accent"),
    cmp: v("--cmp"),
    ok: v("--ok"),
    warn: v("--warn"),
    bad: v("--bad"),
    fg: v("--fg"),
    fg2: v("--fg-2"),
    fg3: v("--fg-3"),
    line: v("--line"),
    view: v("--view"),
  };
  return cache;
}
