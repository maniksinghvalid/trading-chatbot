/**
 * chart.ts — small pure helpers shared by the insight cards (scales, paths,
 * colours, formatting). No DOM, no dependencies; covered by chart.test.ts.
 */

/** Linear map from domain [d0, d1] to range [r0, r1]; a flat domain maps to the range midpoint. */
export function scale(d0: number, d1: number, r0: number, r1: number) {
  const span = d1 - d0;
  return (v: number) => (span === 0 ? (r0 + r1) / 2 : r0 + ((v - d0) / span) * (r1 - r0));
}

/** [min, max] of the finite values padded by `pad` × span (±1 when flat; [0, 1] when empty). */
export function extent(values: number[], pad = 0.05): [number, number] {
  const xs = values.filter(Number.isFinite);
  if (xs.length === 0) return [0, 1];
  const lo = Math.min(...xs);
  const hi = Math.max(...xs);
  const p = hi === lo ? 1 : (hi - lo) * pad;
  return [lo - p, hi + p];
}

/** SVG path through [x, y] points; a null y lifts the pen (gap in the series). */
export function linePath(points: [number, number | null][]): string {
  let d = "";
  let pen = false;
  for (const [x, y] of points) {
    if (y == null || !Number.isFinite(y)) {
      pen = false;
      continue;
    }
    d += `${pen ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`;
    pen = true;
  }
  return d;
}

/** Score → grade/signal bands, mirroring the README table (85+ A+ … 0–24 F). */
export const GRADE_BANDS = [
  { min: 85, grade: "A+", signal: "STRONG BUY", color: "#3ddc97" },
  { min: 70, grade: "A", signal: "BUY", color: "#8fdc5c" },
  { min: 55, grade: "B", signal: "HOLD", color: "#d8c95a" },
  { min: 40, grade: "C", signal: "NEUTRAL", color: "#ffb547" },
  { min: 25, grade: "D", signal: "CAUTION", color: "#ff8a4c" },
  { min: 0, grade: "F", signal: "AVOID", color: "#ff5c6c" },
] as const;

export type GradeBand = (typeof GRADE_BANDS)[number];

export function band(score: number): GradeBand {
  return GRADE_BANDS.find((b) => score >= b.min) ?? GRADE_BANDS[GRADE_BANDS.length - 1];
}

/** Colour for a signal label (case-insensitive); unknown → muted paper. */
export function signalColor(signal: string | null | undefined): string {
  const s = (signal ?? "").toUpperCase();
  return GRADE_BANDS.find((b) => b.signal === s)?.color ?? "#6d6a63";
}

export function money(n: number, approx = false): string {
  const v = n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${approx ? "~" : ""}$${v}`;
}

export function signedMoney(n: number): string {
  return `${n >= 0 ? "+" : "−"}$${Math.abs(n).toFixed(2)}`;
}

/** % distance of `price` from `ref`, e.g. "−11.0%". */
export function pctFrom(price: number, ref: number): string {
  const p = ((price - ref) / ref) * 100;
  return `${p >= 0 ? "+" : "−"}${Math.abs(p).toFixed(1)}%`;
}

/** Whole local days from `from` until an ISO date (YYYY-MM-DD); null if unparseable. */
export function daysUntil(iso: string, from: Date = new Date()): number | null {
  const t = Date.parse(`${iso}T00:00:00`);
  if (Number.isNaN(t)) return null;
  const start = new Date(from.getFullYear(), from.getMonth(), from.getDate()).getTime();
  return Math.round((t - start) / 86_400_000);
}
