"use client";

/**
 * MessageBubble.tsx — renders a single chat message.
 *
 * Security (T-06-01): Content is rendered through ReactMarkdown ONLY.
 * - rehype-raw is NOT enabled (no raw HTML passthrough)
 * - dangerouslySetInnerHTML is NEVER used
 * - No rehype plugins that allow arbitrary HTML injection
 *
 * This ensures LLM output cannot inject executable HTML/JS into the DOM.
 *
 * Polish additions (POLISH-01):
 * - Assistant messages with a quote show a QuoteCard above the text body.
 * - Citations render as expandable CitationCards instead of the flat list.
 * - Ticker symbols detected in assistant content are wrapped in TickerChip.
 */

import ReactMarkdown from "react-markdown";
import type { Citation, Message } from "@/lib/types";
import CitationCard from "./CitationCard";
import QuoteCard from "./QuoteCard";
import TickerChip from "./TickerChip";

interface MessageBubbleProps {
  message: Message;
}

/**
 * Detect uppercase ticker symbols in text that appear in the citations list.
 * Returns a set of ticker strings found in the message body.
 *
 * Strategy: collect all unique tickers from citations, then check which ones
 * appear as whole words in the message content. This avoids false positives
 * (e.g. "I", "A") by only highlighting tickers the backend actually cited.
 */
function detectTickers(content: string, citations: Citation[]): Set<string> {
  const citedTickers = new Set(
    citations.map((c) => c.ticker).filter(Boolean)
  );
  const found = new Set<string>();
  for (const ticker of citedTickers) {
    // Word-boundary match so "AAPL" doesn't trigger inside "SAAPLN"
    const re = new RegExp(`\\b${ticker}\\b`);
    if (re.test(content)) {
      found.add(ticker);
    }
  }
  return found;
}

/**
 * Split plain text into segments, wrapping detected ticker symbols in TickerChip.
 * Preserves the surrounding text as plain string nodes.
 *
 * Called only for the plain-text representation of the message (used in the
 * ticker-chip overlay layer), not inside ReactMarkdown (which handles its own
 * rendering). This function is intentionally kept outside the ReactMarkdown
 * render tree to preserve T-06-01.
 */
function renderWithTickerChips(
  text: string,
  tickers: Set<string>
): React.ReactNode[] {
  if (tickers.size === 0) return [text];

  // Build a single regex from all tickers, longest first to avoid prefix clobber
  const sorted = [...tickers].sort((a, b) => b.length - a.length);
  const pattern = sorted.map((t) => `\\b${t}\\b`).join("|");
  const re = new RegExp(`(${pattern})`, "g");

  const parts = text.split(re);
  return parts.map((part, i) =>
    tickers.has(part) ? (
      <TickerChip key={`${part}-${i}`} ticker={part} />
    ) : (
      part
    )
  );
}

/**
 * Citations section rendered below assistant bubbles.
 * Each citation renders as an expandable CitationCard.
 */
function Citations({ citations }: { citations: Citation[] }) {
  if (!citations || citations.length === 0) return null;

  return (
    <div className="mt-3 pt-3 border-t border-gray-700">
      <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
        Sources
      </p>
      <div className="space-y-1.5">
        {citations.map((c, i) => (
          <CitationCard key={`${c.source_path}-${i}`} citation={c} index={i} />
        ))}
      </div>
    </div>
  );
}

export default function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const citations = message.citations ?? [];
  const tickers = isUser ? new Set<string>() : detectTickers(message.content, citations);

  return (
    <div
      className={`flex w-full ${isUser ? "justify-end" : "justify-start"} mb-4`}
    >
      <div
        className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
          isUser
            ? "bg-blue-600 text-white rounded-br-sm"
            : "bg-gray-800 text-gray-100 rounded-bl-sm"
        }`}
      >
        {/* Live quote card — shown above the text body for assistant messages (02-02) */}
        {!isUser && message.quote && (
          <QuoteCard quote={message.quote} />
        )}

        {/* ReactMarkdown renders LLM output safely — no rehype-raw, no raw HTML (T-06-01) */}
        <div className="prose prose-sm prose-invert max-w-none">
          <ReactMarkdown
            components={{
              // Override anchor to open in new tab safely
              a: ({ href, children }) => (
                <a
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-400 underline"
                >
                  {children}
                </a>
              ),
              // Override code blocks for better styling
              code: ({ className, children, ...props }) => {
                const isInline = !className;
                return isInline ? (
                  <code
                    className="bg-gray-700 px-1 py-0.5 rounded text-xs font-mono"
                    {...props}
                  >
                    {children}
                  </code>
                ) : (
                  <code
                    className={`block bg-gray-900 p-3 rounded text-xs font-mono overflow-x-auto ${className ?? ""}`}
                    {...props}
                  >
                    {children}
                  </code>
                );
              },
              // Override paragraph to inject TickerChip for detected tickers (T-06-01 preserved:
              // we split plain text strings only — no raw HTML, no dangerouslySetInnerHTML)
              p: ({ children }) => {
                if (tickers.size === 0 || isUser) {
                  return <p>{children}</p>;
                }
                // Map each child node: string nodes get ticker-chip splitting, others pass through
                const enhanced = Array.isArray(children)
                  ? children.flatMap((child, i) =>
                      typeof child === "string"
                        ? renderWithTickerChips(child, tickers).map((node, j) => (
                            <span key={`tc-${i}-${j}`}>{node}</span>
                          ))
                        : [<span key={`pass-${i}`}>{child}</span>]
                    )
                  : typeof children === "string"
                  ? renderWithTickerChips(children, tickers)
                  : children;
                return <p>{enhanced}</p>;
              },
            }}
          >
            {message.content || (isUser ? "" : "■")}
          </ReactMarkdown>
        </div>

        {/* Citations — only rendered for assistant messages with citations */}
        {!isUser && citations.length > 0 && (
          <Citations citations={citations} />
        )}
      </div>
    </div>
  );
}
