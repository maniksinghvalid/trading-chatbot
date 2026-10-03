/**
 * KeyLevelsCard.tsx — price ladder: resistance above (loss tint), support below
 * (gain tint), current price in amber. Labels are de-collided with leader lines.
 */
import type { KeyLevelsInsight } from "@/lib/types";
import { extent, money, pctFrom, scale } from "@/lib/chart";
import InsightCard from "./InsightCard";

const W = 330;
const TRACK = 16;
const LABEL = 44;
const GAP = 18;
const PAD = 14;

function short(label: string): string {
  return label.length > 22 ? `${label.slice(0, 21)}…` : label;
}

export default function KeyLevelsCard({ data, className }: { data: KeyLevelsInsight; className?: string }) {
  const rows = [
    ...data.levels.map((l) => ({ ...l, now: false })),
    { label: "Now", price: data.price, note: null, approx: false, now: true },
  ].sort((a, b) => b.price - a.price);
  const [lo, hi] = extent(rows.map((r) => r.price), 0.04);
  const base = Math.max(220, rows.length * GAP + 2 * PAD);
  const y = scale(hi, lo, PAD, base - PAD);
  let prev = -Infinity;
  const placed = rows.map((r) => {
    const ly = Math.max(y(r.price), prev + GAP);
    prev = ly;
    return { ...r, ty: y(r.price), ly };
  });
  const H = Math.max(base, prev + PAD);
  const summary = `Key levels around ${money(data.price)}: ` + data.levels.map((l) => `${l.label} ${money(l.price)}`).join("; ");

  return (
    <InsightCard title="Key levels" source={data.source} className={className}>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={summary}>
        <line x1={TRACK} x2={TRACK} y1={PAD} y2={base - PAD} stroke="#2a3142" strokeWidth="2" />
        {placed.map((r) => {
          const color = r.now ? "#ffb547" : r.price > data.price ? "#ff5c6c" : "#3ddc97";
          return (
            <g key={`${r.label}-${r.price}`}>
              <title>{r.note ?? r.label}</title>
              <line x1={TRACK - 6} x2={TRACK + 6} y1={r.ty} y2={r.ty} stroke={color} strokeWidth={r.now ? 3 : 2} />
              <path d={`M${TRACK + 6},${r.ty} L${LABEL - 6},${r.ly}`} stroke={color} strokeOpacity="0.4" fill="none" />
              <text x={LABEL} y={r.ly + 4} fontSize="12" className="font-mono" fill={color}>
                {money(r.price, r.approx)}
              </text>
              <text x={LABEL + 70} y={r.ly + 4} fontSize="12" className={r.now ? "fill-amber-glow" : "fill-paper-dim"}>
                {short(r.label)}
              </text>
              {!r.now && (
                <text x={W} y={r.ly + 4} textAnchor="end" fontSize="11" className="fill-paper-mute font-mono">
                  {pctFrom(r.price, data.price)}
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </InsightCard>
  );
}
