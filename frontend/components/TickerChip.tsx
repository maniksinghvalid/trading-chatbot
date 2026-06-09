"use client";

/**
 * TickerChip.tsx — small pill component highlighting a ticker symbol.
 *
 * Used by MessageBubble to wrap detected ticker symbols (e.g. AAPL, NVDA)
 * in assistant messages, making them visually distinct from surrounding text.
 *
 * Ticker detection in MessageBubble uses a simple uppercase-symbol match
 * (regex \b[A-Z]{1,5}\b) against known tickers extracted from citations.
 * This stays entirely client-side — no network calls.
 *
 * Security (T-06-01): Renders only plain text (the ticker symbol string).
 * No raw HTML, no dangerouslySetInnerHTML.
 */

interface TickerChipProps {
  /** The uppercase ticker symbol to display, e.g. "AAPL". */
  ticker: string;
}

export default function TickerChip({ ticker }: TickerChipProps) {
  return (
    <span
      className="inline-block bg-blue-900/50 text-blue-300 text-xs font-mono font-semibold
                 px-1.5 py-0.5 rounded border border-blue-700/50 mx-0.5 align-baseline"
      aria-label={`Ticker: ${ticker}`}
    >
      {ticker}
    </span>
  );
}
