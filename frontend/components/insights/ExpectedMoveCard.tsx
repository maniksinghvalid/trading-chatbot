/**
 * ExpectedMoveCard.tsx — 1W / 1M / 90D expected-move bands on a price axis.
 * HTML rather than SVG text so labels keep their size at phone widths.
 */
import { Fragment } from "react";
import type { ExpectedMoveInsight } from "@/lib/types";
import { extent, money, scale } from "@/lib/chart";
import InsightCard from "./InsightCard";

export default function ExpectedMoveCard({ data, className }: { data: ExpectedMoveInsight; className?: string }) {
  const [lo, hi] = extent([...data.ranges.flatMap((r) => [r.low, r.high]), data.price], 0.04);
  const pct = scale(lo, hi, 0, 100);
  const now = `${pct(data.price)}%`;
  const summary =
    `Expected move from ${money(data.price)}: ` +
    data.ranges.map((r) => `${r.label} ${money(r.low)} to ${money(r.high)}`).join("; ");

  return (
    <InsightCard title="Expected move" source={data.source} className={className}>
      <div role="img" aria-label={summary} className="grid grid-cols-[7rem_1fr] gap-x-3 sm:grid-cols-[9rem_1fr]">
        <span />
        <div className="relative h-5">
          <span
            className="absolute -translate-x-1/2 whitespace-nowrap font-mono text-[11px] text-amber-glow"
            style={{ left: now }}
          >
            now {money(data.price)}
          </span>
        </div>
        {data.ranges.map((r, i) => (
          <Fragment key={r.label}>
            <div className="py-1.5">
              <p className="truncate text-xs text-paper-dim" title={r.label}>
                {r.label}
              </p>
              <p className="font-mono text-[10px] text-paper-mute">
                {money(r.low, r.approx)}–{money(r.high, r.approx)}
                {r.pct != null && ` · ±${r.pct}%`}
              </p>
            </div>
            <div className="relative">
              <span
                className="absolute top-1/2 h-3 -translate-y-1/2 rounded bg-amber-glow"
                style={{
                  left: `${pct(r.low)}%`,
                  width: `${pct(r.high) - pct(r.low)}%`,
                  opacity: Math.max(0.18, 0.6 - i * 0.14),
                }}
              />
              <span className="absolute inset-y-0 w-0.5 -translate-x-1/2 bg-amber-glow" style={{ left: now }} />
            </div>
          </Fragment>
        ))}
        <span />
        <div className="mt-1 flex justify-between border-t border-ink-700 pt-1 font-mono text-[10px] text-paper-mute">
          <span>{money(lo)}</span>
          <span>{money(hi)}</span>
        </div>
      </div>
    </InsightCard>
  );
}
