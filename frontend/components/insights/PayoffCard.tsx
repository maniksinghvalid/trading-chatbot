/**
 * PayoffCard.tsx — at-expiry P/L curve for the recommended strategy, computed by the
 * backend from the report's legs. Gain area green, loss area red, strikes dashed.
 */
import { useId } from "react";
import type { StrategyInsight } from "@/lib/types";
import { extent, linePath, money, scale, signedMoney } from "@/lib/chart";
import InsightCard from "./InsightCard";

const W = 560;
const H = 220;
const L = 46;
const R = 12;
const T = 16;
const B = 26;

export default function PayoffCard({ data, className }: { data: StrategyInsight; className?: string }) {
  const clip = useId().replace(/:/g, "");
  const xs = data.curve.map((c) => c[0]);
  const ys = data.curve.map((c) => c[1]);
  const x0 = Math.min(...xs);
  const x1 = Math.max(...xs);
  const [y0, y1] = extent([...ys, 0], 0.15);
  const x = scale(x0, x1, L, W - R);
  const y = scale(y0, y1, H - B, T);
  const line = linePath(data.curve.map(([a, b]) => [x(a), y(b)]));
  const zero = y(0);
  const area = `${line}L${x(x1).toFixed(1)},${zero.toFixed(1)}L${x(x0).toFixed(1)},${zero.toFixed(1)}Z`;
  const strikes = Array.from(new Set(data.legs.map((l) => l.strike)));
  const maxGain = data.max_gain == null ? "Unlimited" : signedMoney(data.max_gain);
  const maxLoss = data.max_loss == null ? "Unlimited" : signedMoney(data.max_loss);
  const summary =
    `${data.name} payoff at expiration: max loss ${maxLoss}, max gain ${maxGain}` +
    (data.breakevens.length ? `, breakeven ${data.breakevens.map((b) => money(b)).join(" and ")}` : "");

  return (
    <InsightCard title={`${data.name} · payoff at ${data.expiration}`} source={data.source} className={className}>
      <div className="mb-2 flex flex-wrap gap-x-5 gap-y-1 font-mono text-[11px] text-paper-mute">
        <span>
          Max gain <span className="text-gain">{maxGain}</span>
        </span>
        <span>
          Max loss <span className="text-loss">{maxLoss}</span>
        </span>
        {data.breakevens.map((b) => (
          <span key={b}>
            Breakeven <span className="text-paper">{money(b)}</span>
          </span>
        ))}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={summary}>
        <defs>
          <clipPath id={`${clip}-up`}>
            <rect x="0" y="0" width={W} height={zero} />
          </clipPath>
          <clipPath id={`${clip}-down`}>
            <rect x="0" y={zero} width={W} height={H - zero} />
          </clipPath>
        </defs>
        <path d={area} fill="#3ddc97" opacity="0.18" clipPath={`url(#${clip}-up)`} />
        <path d={area} fill="#ff5c6c" opacity="0.18" clipPath={`url(#${clip}-down)`} />
        <line x1={L} x2={W - R} y1={zero} y2={zero} stroke="#6d6a63" />
        <text x={L - 6} y={zero + 4} textAnchor="end" fontSize="11" className="fill-paper-mute font-mono">$0</text>
        {strikes.map((k) => (
          <g key={k}>
            <line x1={x(k)} x2={x(k)} y1={T} y2={H - B} stroke="#2a3142" strokeDasharray="3 4" />
            <text x={x(k)} y={H - 8} textAnchor="middle" fontSize="11" className="fill-paper-dim font-mono">
              {money(k)}
            </text>
          </g>
        ))}
        <path d={line} fill="none" stroke="#ece6d9" strokeWidth="2" strokeLinejoin="round" />
        {data.breakevens.map((b) => (
          <circle key={b} cx={x(b)} cy={zero} r="4" fill="#ffb547" />
        ))}
        <line x1={x(data.price)} x2={x(data.price)} y1={T} y2={H - B} stroke="#ffb547" strokeOpacity="0.7" />
        <text x={x(data.price) + 4} y={T + 10} fontSize="11" className="fill-amber-glow font-mono">
          now {money(data.price)}
        </text>
      </svg>
      <table className="mt-3 w-full font-mono text-[11px]">
        <tbody>
          {data.includes_stock && (
            <tr className="border-t border-ink-700">
              <td className="py-1.5 text-gain">Long</td>
              <td className="text-paper">Stock</td>
              <td className="text-paper-dim">{money(data.price)}</td>
              <td className="text-paper-mute">cost basis</td>
            </tr>
          )}
          {data.legs.map((l, i) => (
            <tr key={i} className="border-t border-ink-700">
              <td className={`py-1.5 ${l.action === "buy" ? "text-gain" : "text-loss"}`}>{l.action === "buy" ? "Buy" : "Sell"}</td>
              <td className="text-paper">
                {money(l.strike)} {l.type === "call" ? "Call" : "Put"}
              </td>
              <td className="text-paper-dim">{money(l.premium, l.approx)}</td>
              <td className="text-paper-mute">{data.expiration}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-[10px] text-paper-mute">
        Per share at expiration · premiums as quoted in report · ignores fees and early assignment
      </p>
    </InsightCard>
  );
}
