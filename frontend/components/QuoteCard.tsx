"use client";

/**
 * QuoteCard.tsx — distinct live market-data quote card.
 *
 * Renders {price, day_change_pct (green/red), volume, timestamp, source}
 * with a small "~15 min delayed" note. Styled distinctly from CitationCard
 * so the user can clearly distinguish live quotes from cited memory.
 *
 * Receives a Quote object from ChatWindow (sourced from the SSE quote event
 * added in 02-02 via market_data.py + yfinance).
 *
 * Security (T-06-01): No raw HTML rendered; all content is plain text in JSX.
 * No rehype-raw, no dangerouslySetInnerHTML.
 */

import type { Quote } from "@/lib/types";

interface QuoteCardProps {
  quote: Quote;
}

/** Format a number as a price string with 2 decimal places. */
function formatPrice(n: number): string {
  return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** Format volume compactly, e.g. 48.2M. */
function formatVolume(n: number): string {
  return n.toLocaleString("en-US", { notation: "compact", maximumFractionDigits: 1 });
}

/** Format an ISO timestamp into a human-readable local time. */
function formatTimestamp(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return iso;
  }
}

export default function QuoteCard({ quote }: QuoteCardProps) {
  const isPositive = quote.day_change_pct >= 0;
  const changeSign = isPositive ? "+" : "";
  const tone = isPositive
    ? { text: "text-gain", pill: "bg-gain/15 border-gain/30", glow: "from-gain/20", arrow: "▲" }
    : { text: "text-loss", pill: "bg-loss/15 border-loss/30", glow: "from-loss/20", arrow: "▼" };

  return (
    <div className="relative mb-5 overflow-hidden rounded-2xl border border-ink-600 bg-ink-900">
      {/* Direction-tinted wash */}
      <div className={`pointer-events-none absolute inset-0 bg-gradient-to-br ${tone.glow} via-transparent to-transparent`} />

      <div className="relative px-5 py-4">
        <div className="flex items-center justify-between font-mono text-[10px] uppercase tracking-[0.2em]">
          <span className="flex items-center gap-1.5 text-paper-dim">
            <span className={`h-1.5 w-1.5 animate-pulse rounded-full ${isPositive ? "bg-gain" : "bg-loss"}`} />
            Live quote
          </span>
          <span className="text-paper-mute">~15 min delayed · {quote.source}</span>
        </div>

        <div className="mt-3 flex flex-wrap items-baseline gap-x-4 gap-y-2">
          <span className="font-mono text-4xl font-semibold tracking-tight tabular-nums text-paper">
            <span className="mr-0.5 text-2xl text-paper-mute">$</span>
            {formatPrice(quote.price)}
          </span>
          <span
            className={`rounded-full border px-2.5 py-0.5 font-mono text-sm font-medium tabular-nums ${tone.text} ${tone.pill}`}
          >
            {tone.arrow} {changeSign}
            {quote.day_change_pct.toFixed(2)}%
          </span>
        </div>

        <div className="mt-3 flex gap-6 border-t border-ink-700/80 pt-3 font-mono text-[11px] text-paper-mute">
          <span>
            VOL <span className="text-paper-dim">{formatVolume(quote.volume)}</span>
          </span>
          <span>
            AS OF <span className="text-paper-dim">{formatTimestamp(quote.timestamp)}</span>
          </span>
        </div>
      </div>
    </div>
  );
}
