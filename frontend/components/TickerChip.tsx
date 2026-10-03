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
      className="mx-0.5 inline-flex items-baseline rounded-md border border-amber-glow/25 bg-amber-glow/[0.08] px-1.5 font-mono text-[0.82em] font-semibold text-amber-glow"
      aria-label={`Ticker: ${ticker}`}
    >
      <span className="mr-px opacity-50">$</span>
      {ticker}
    </span>
  );
}
