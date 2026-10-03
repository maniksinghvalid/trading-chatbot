/**
 * ScoreCard.tsx — composite trade score gauge (bands = README grade table),
 * dimension bars with weights, price / stop / catalyst, 30-run sparklines.
 */
import type { ScoreInsight, TrendInsight } from "@/lib/types";
import { GRADE_BANDS, band, daysUntil, money, pctFrom, signalColor } from "@/lib/chart";
import InsightCard from "./InsightCard";
import Sparkline from "./Sparkline";

const CX = 100;
const CY = 96;
const R = 80;

/** Point on the gauge arc for a 0–100 score (0 = left, 100 = right). */
function arcPoint(score: number, r = R): [number, number] {
  const t = Math.PI * (1 - Math.min(100, Math.max(0, score)) / 100);
  return [CX + r * Math.cos(t), CY - r * Math.sin(t)];
}

function arc(from: number, to: number): string {
  const [x0, y0] = arcPoint(from);
  const [x1, y1] = arcPoint(to);
  return `M${x0.toFixed(1)},${y0.toFixed(1)} A${R},${R} 0 0 1 ${x1.toFixed(1)},${y1.toFixed(1)}`;
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-wider text-paper-mute">{label}</dt>
      <dd className="mt-0.5 text-paper">
        {value}
        {sub && <span className="ml-1.5 text-[10px] text-paper-mute">{sub}</span>}
      </dd>
    </div>
  );
}

export default function ScoreCard({
  score,
  trend,
  className,
}: {
  score: ScoreInsight;
  trend?: TrendInsight;
  className?: string;
}) {
  const current = band(score.composite);
  const [nx, ny] = arcPoint(score.composite, R - 18);
  const recent = trend?.points.slice(-30) ?? [];
  const days = score.catalyst_date ? daysUntil(score.catalyst_date) : null;
  const grade = score.grade ?? current.grade;
  const signal = score.signal ?? current.signal;

  return (
    <InsightCard title="Trade score" source={score.source} className={className}>
      <div className="flex flex-col gap-5 sm:flex-row sm:items-center">
        <svg
          viewBox="0 0 200 104"
          className="w-full max-w-[200px] flex-shrink-0"
          role="img"
          aria-label={`Trade score ${score.composite} of 100, grade ${grade}, signal ${signal}`}
        >
          {GRADE_BANDS.map((b, i) => (
            <path
              key={b.grade}
              d={arc(b.min + 0.8, (i === 0 ? 100 : GRADE_BANDS[i - 1].min) - 0.8)}
              stroke={b.color}
              strokeWidth="10"
              fill="none"
              opacity={b === current ? 1 : 0.22}
            />
          ))}
          <line x1={CX} y1={CY} x2={nx} y2={ny} stroke="#ece6d9" strokeWidth="2.5" strokeLinecap="round" />
          <circle cx={CX} cy={CY} r="5" fill="#ece6d9" />
        </svg>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="font-mono text-4xl font-semibold text-paper">{score.composite}</span>
            <span className="font-mono text-sm text-paper-mute">/100</span>
            <span
              className="rounded-md border px-2 py-0.5 font-mono text-xs"
              style={{ color: current.color, borderColor: `${current.color}66` }}
            >
              {grade}
            </span>
            <span
              className="rounded-full px-2.5 py-0.5 font-mono text-[11px] uppercase tracking-wider text-ink-950"
              style={{ background: signalColor(signal) }}
            >
              {signal}
            </span>
          </div>
          <ul className="mt-4 space-y-2">
            {score.dimensions.map((d) => (
              <li key={d.name} className="grid grid-cols-[88px_1fr_28px_34px] items-center gap-2 text-xs">
                <span className="text-paper-dim">{d.name}</span>
                <span className="h-1.5 overflow-hidden rounded-full bg-ink-700">
                  <span
                    className="block h-full rounded-full"
                    style={{ width: `${Math.min(100, d.score)}%`, background: band(d.score).color }}
                  />
                </span>
                <span className="text-right font-mono tabular-nums text-paper">{d.score}</span>
                <span className="text-right font-mono text-[10px] text-paper-mute">{Math.round(d.weight * 100)}%</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-3 border-t border-ink-700/70 pt-3 font-mono text-[11px] sm:grid-cols-4">
        {score.price != null && <Stat label="Price" value={money(score.price)} />}
        {score.stop_loss != null && (
          <Stat
            label="Stop"
            value={money(score.stop_loss)}
            sub={score.price ? pctFrom(score.stop_loss, score.price) : undefined}
          />
        )}
        {days != null && days >= 0 && <Stat label="Catalyst" value={`${days}d`} sub={score.catalyst_date ?? undefined} />}
        {recent.length >= 2 && (
          <div>
            <dt className="text-[10px] uppercase tracking-wider text-paper-mute">Last {recent.length} runs</dt>
            <dd className="mt-1 flex gap-2">
              <Sparkline values={recent.map((p) => p.price)} color="#ece6d9" width={56} height={20} label="Price trend" />
              <Sparkline values={recent.map((p) => p.score)} width={56} height={20} label="Score trend" />
            </dd>
          </div>
        )}
      </dl>
    </InsightCard>
  );
}
