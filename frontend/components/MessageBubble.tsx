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

import type { Citation, Message } from "@/lib/types";
import CitationCard from "./CitationCard";
import QuoteCard from "./QuoteCard";
import StreamingMarkdown from "./StreamingMarkdown";

interface MessageBubbleProps {
  message: Message;
  /**
   * Pass true when this bubble is the assistant's actively-streaming message.
   * Forwarded to StreamingMarkdown to enable debounced parsing during streaming
   * and immediate flush on completion.
   */
  isStreaming?: boolean;
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

export default function MessageBubble({ message, isStreaming = false }: MessageBubbleProps) {
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

        {/*
          Assistant messages use StreamingMarkdown for debounced incremental rendering
          (smooth token streaming, flush on completion). User messages are static —
          rendered through the same safe ReactMarkdown config inside StreamingMarkdown.
          T-06-01: StreamingMarkdown uses no rehype-raw, no dangerouslySetInnerHTML.
        */}
        {isUser ? (
          /* User bubbles: static plain text — no markdown parsing needed */
          <p className="whitespace-pre-wrap">{message.content}</p>
        ) : (
          <StreamingMarkdown
            content={message.content}
            streaming={isStreaming}
            tickers={tickers}
          />
        )}

        {/* Citations — only rendered for assistant messages with citations */}
        {!isUser && citations.length > 0 && (
          <Citations citations={citations} />
        )}
      </div>
    </div>
  );
}
