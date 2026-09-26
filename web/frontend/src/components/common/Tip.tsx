import { useEffect, useState, type CSSProperties } from "react";

/** Кружок «?» с подсказкой; сама подсказка рисуется поверх окна слоем TipLayer. */
export function Tip({ text, style }: { text: string; style?: CSSProperties }) {
  return (
    <span className="tip" tabIndex={0} data-tip={text} style={style}>
      ?
    </span>
  );
}

interface Box {
  text: string;
  anchor: DOMRect;
}

/** Всплывающая подсказка поверх окна: справа от «?», не выходит за край экрана. */
export function TipLayer() {
  const [box, setBox] = useState<Box | null>(null);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);

  useEffect(() => {
    const show = (t: HTMLElement) => {
      const text = t.dataset.tip;
      setPos(null);
      setBox(text ? { text, anchor: t.getBoundingClientRect() } : null);
    };
    const over = (e: MouseEvent) => {
      const t = (e.target as HTMLElement).closest?.(".tip") as HTMLElement | null;
      if (t) show(t);
    };
    const out = (e: MouseEvent) => {
      if ((e.target as HTMLElement).closest?.(".tip")) setBox(null);
    };
    const fin = (e: FocusEvent) => {
      const t = e.target as HTMLElement;
      if (t.classList && t.classList.contains("tip")) show(t);
    };
    const fout = () => setBox(null);
    document.addEventListener("mouseover", over);
    document.addEventListener("mouseout", out);
    document.addEventListener("focusin", fin);
    document.addEventListener("focusout", fout);
    return () => {
      document.removeEventListener("mouseover", over);
      document.removeEventListener("mouseout", out);
      document.removeEventListener("focusin", fin);
      document.removeEventListener("focusout", fout);
    };
  }, []);

  if (!box) return null;
  const place = (el: HTMLDivElement | null) => {
    if (!el || pos) return;
    const r = box.anchor,
      bw = el.offsetWidth,
      bh = el.offsetHeight;
    let x = r.right + 10,
      y = r.top - 6;
    if (x + bw > window.innerWidth - 8) x = r.left - bw - 10;
    if (x < 8) x = 8;
    if (y + bh > window.innerHeight - 8) y = window.innerHeight - bh - 8;
    setPos({ left: x, top: Math.max(8, y) });
  };
  return (
    <div className="tipbox" ref={place} style={pos ? pos : { left: -9999, top: 0 }}>
      {box.text}
    </div>
  );
}
