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

/** Format volume with comma separators. */
function formatVolume(n: number): string {
  return n.toLocaleString("en-US");
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
  const changeColor = isPositive ? "text-green-400" : "text-red-400";

  return (
    <div className="rounded-xl border border-blue-800 bg-blue-950/40 px-4 py-3 mb-3 text-sm">
      {/* Header row */}
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-blue-300 uppercase tracking-wide">
          Live Quote
        </span>
        <span className="text-xs text-gray-500">
          ~15 min delayed &bull; {quote.source}
        </span>
      </div>

      {/* Price row */}
      <div className="flex items-baseline gap-3">
        <span className="text-2xl font-bold text-white">
          ${formatPrice(quote.price)}
        </span>
        <span className={`text-sm font-medium ${changeColor}`}>
          {changeSign}{quote.day_change_pct.toFixed(2)}%
        </span>
      </div>

      {/* Secondary row: volume + timestamp */}
      <div className="flex items-center gap-4 mt-1.5 text-xs text-gray-400">
        <span>Vol: {formatVolume(quote.volume)}</span>
        <span>As of {formatTimestamp(quote.timestamp)}</span>
      </div>
    </div>
  );
}
