import { useEffect, useRef, useState } from "react";

export type Series = { id: string; label: string; color: string };

export const MARGIN = { top: 10, right: 14, bottom: 28, left: 48 };

/** Tracks an element's width so SVG charts can render at real pixel size. */
export function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

export function linear(domain: [number, number], range: [number, number]) {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  const k = d1 === d0 ? 0 : (r1 - r0) / (d1 - d0);
  return (v: number) => r0 + (v - d0) * k;
}

export function logScale(domain: [number, number], range: [number, number]) {
  const f = linear([Math.log10(domain[0]), Math.log10(domain[1])], range);
  return (v: number) => f(Math.log10(Math.max(v, 1e-12)));
}

/** Round tick values covering [min, max]. */
export function niceTicks(min: number, max: number, count = 4): number[] {
  if (!(max > min)) max = min + 1;
  const rough = (max - min) / count;
  const mag = 10 ** Math.floor(Math.log10(rough));
  const err = rough / mag;
  const step = (err >= 7.5 ? 10 : err >= 3.5 ? 5 : err >= 1.5 ? 2 : 1) * mag;
  const ticks = [];
  for (let v = Math.floor(min / step) * step; v <= Math.ceil(max / step) * step + step / 2; v += step) {
    ticks.push(+v.toPrecision(12));
  }
  return ticks;
}

/** Powers of ten (and 2x, 5x when the span is short) inside [min, max]. */
export function logTicks(min: number, max: number): number[] {
  const decades = Math.log10(max / min);
  const multipliers = decades <= 1.5 ? [1, 2, 5] : [1];
  const ticks = [];
  for (let e = Math.floor(Math.log10(min)); e <= Math.ceil(Math.log10(max)); e++) {
    for (const m of multipliers) {
      const v = m * 10 ** e;
      if (v >= min * 0.999 && v <= max * 1.001) ticks.push(+v.toPrecision(6));
    }
  }
  return ticks;
}

/** A column with a 4px rounded data end and a square baseline. */
export function columnPath(x: number, y: number, w: number, h: number, r = 4) {
  if (h <= 0 || w <= 0) return "";
  const rr = Math.min(r, w / 2, h);
  return `M${x},${y + h}V${y + rr}Q${x},${y} ${x + rr},${y}H${x + w - rr}Q${x + w},${y} ${x + w},${y + rr}V${y + h}Z`;
}
