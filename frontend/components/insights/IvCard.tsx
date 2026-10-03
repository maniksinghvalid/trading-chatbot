/** IvCard.tsx — IV rank meter (0–100) with IV-rank history sparkline. */
import type { IvInsight, TrendInsight } from "@/lib/types";
import InsightCard from "./InsightCard";
import Sparkline from "./Sparkline";

export default function IvCard({ iv, trend, className }: { iv: IvInsight; trend?: TrendInsight; className?: string }) {
  const history = trend?.points.map((p) => p.iv_rank) ?? [];
  const pos = Math.min(100, Math.max(0, iv.iv_rank));
  return (
    <InsightCard title="Implied volatility" source={iv.source} className={className}>
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-3xl font-semibold text-paper">{iv.iv_rank}</span>
        <span className="font-mono text-xs text-paper-mute">IV rank · 52-week</span>
      </div>
      <div
        className="relative mt-3 h-2 rounded-full bg-gradient-to-r from-ink-700 via-[#b9a4ff]/40 to-[#b9a4ff]"
        role="img"
        aria-label={`IV rank ${iv.iv_rank} of 100`}
      >
        <span className="absolute -top-1 h-4 w-1 -translate-x-1/2 rounded bg-paper" style={{ left: `${pos}%` }} />
      </div>
      <div className="mt-1 flex justify-between font-mono text-[10px] text-paper-mute">
        <span>0</span>
        <span>50</span>
        <span>100</span>
      </div>
      {history.filter((v) => v != null).length >= 2 && (
        <div className="mt-3 flex items-center gap-3">
          <span className="font-mono text-[10px] uppercase tracking-wider text-paper-mute">History</span>
          <Sparkline values={history} color="#b9a4ff" width={160} height={28} label="IV rank history" />
        </div>
      )}
    </InsightCard>
  );
}
