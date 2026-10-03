"use client";

/**
 * TrendCard.tsx — price / score / IV-rank lines on a shared date axis plus a
 * signal-coloured strip; hovering any row moves a shared readout.
 */
import { useState, type MouseEvent } from "react";
import type { TrendInsight, TrendPoint } from "@/lib/types";
import { extent, linePath, money, scale, signalColor } from "@/lib/chart";
import InsightCard from "./InsightCard";

const W = 520;
const H = 56;

const SERIES: { key: "price" | "score" | "iv_rank"; label: string; color: string; fmt: (v: number) => string }[] = [
  { key: "price", label: "Price", color: "#ece6d9", fmt: (v) => money(v) },
  { key: "score", label: "Score", color: "#ffb547", fmt: (v) => String(v) },
  { key: "iv_rank", label: "IV rank", color: "#b9a4ff", fmt: (v) => `${v}%` },
];

function readout(p: TrendPoint): string {
  const parts = SERIES.filter((s) => p[s.key] != null).map((s) => `${s.label} ${s.fmt(p[s.key] as number)}`);
  return [p.date, ...parts, p.signal].filter(Boolean).join(" · ");
}

export default function TrendCard({ trend, className }: { trend: TrendInsight; className?: string }) {
  const pts = trend.points;
  const [hover, setHover] = useState<number | null>(null);
  const x = scale(0, pts.length - 1, 0, W);
  const active = hover ?? pts.length - 1;

  function onMove(e: MouseEvent<SVGSVGElement>) {
    const r = e.currentTarget.getBoundingClientRect();
    const i = Math.round(((e.clientX - r.left) / r.width) * (pts.length - 1));
    setHover(Math.min(pts.length - 1, Math.max(0, i)));
  }

  return (
    <InsightCard title={`Trend · last ${pts.length} reports`} className={className}>
      <p className="mb-3 min-h-[1rem] font-mono text-[11px] text-paper-dim">{readout(pts[active])}</p>
      {SERIES.map((s) => {
        const vals = pts.map((p) => p[s.key] ?? null);
        const nums = vals.filter((v): v is number => v != null);
        if (nums.length < 2) return null;
        const [lo, hi] = extent(nums);
        const y = scale(lo, hi, H - 4, 4);
        const delta = nums[nums.length - 1] - nums[0];
        const deltaText = s.key === "price" ? `$${Math.abs(delta).toFixed(2)}` : Math.abs(delta).toFixed(0);
        return (
          <div key={s.key} className="mb-2 grid grid-cols-[56px_1fr_64px] items-center gap-3">
            <span className="font-mono text-[10px] uppercase tracking-wider text-paper-mute">{s.label}</span>
            <svg
              viewBox={`0 0 ${W} ${H}`}
              preserveAspectRatio="none"
              className="h-14 w-full cursor-crosshair"
              onMouseMove={onMove}
              onMouseLeave={() => setHover(null)}
              role="img"
              aria-label={`${s.label} from ${s.fmt(nums[0])} to ${s.fmt(nums[nums.length - 1])}`}
            >
              <path
                d={linePath(vals.map((v, i) => [x(i), v == null ? null : y(v)]))}
                fill="none"
                stroke={s.color}
                strokeWidth="1.5"
                vectorEffect="non-scaling-stroke"
              />
              <line
                x1={x(active)}
                x2={x(active)}
                y1="0"
                y2={H}
                stroke="#6d6a63"
                strokeDasharray="2 3"
                vectorEffect="non-scaling-stroke"
              />
            </svg>
            <span className={`text-right font-mono text-[11px] ${delta >= 0 ? "text-gain" : "text-loss"}`}>
              {delta >= 0 ? "▲" : "▼"} {deltaText}
            </span>
          </div>
        );
      })}
      <div className="mt-1 grid grid-cols-[56px_1fr_64px] items-center gap-3">
        <span className="font-mono text-[10px] uppercase tracking-wider text-paper-mute">Signal</span>
        <svg
          viewBox={`0 0 ${pts.length} 1`}
          preserveAspectRatio="none"
          className="h-3 w-full cursor-crosshair rounded-sm"
          onMouseMove={onMove}
          onMouseLeave={() => setHover(null)}
          role="img"
          aria-label={`Signal from ${pts[0].signal ?? "unknown"} to ${pts[pts.length - 1].signal ?? "unknown"}`}
        >
          {pts.map((p, i) => (
            <rect key={p.date} x={i} y="0" width="1.02" height="1" fill={signalColor(p.signal)} opacity={i === active ? 1 : 0.65} />
          ))}
        </svg>
        <span />
      </div>
    </InsightCard>
  );
}
