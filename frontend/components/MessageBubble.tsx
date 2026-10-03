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
 *
 * Night Desk layout: user turns render as serif "headlines"; assistant turns
 * render as memos hanging off a timeline rule, with source tiles beneath.
 */

import type { Citation, Message } from "@/lib/types";
import CitationCard from "./CitationCard";
import QuoteCard from "./QuoteCard";
import InsightsPanel from "./insights/InsightsPanel";
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
 * Citations section rendered below assistant answers.
 * Each citation renders as an expandable CitationCard tile.
 */
function Citations({ citations }: { citations: Citation[] }) {
  if (!citations || citations.length === 0) return null;

  return (
    <div className="mt-6">
      <p className="mb-2.5 flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.22em] text-paper-mute">
        Sources
        <span className="h-px flex-1 bg-ink-700" />
        <span className="tabular-nums">{String(citations.length).padStart(2, "0")}</span>
      </p>
      <div className="grid gap-2 sm:grid-cols-2">
        {citations.map((c, i) => (
          <CitationCard key={`${c.source_path}-${i}`} citation={c} index={i} />
        ))}
      </div>
    </div>
  );
}

/** Equalizer bars — the desk's "working" glyph. */
function Bars() {
  return (
    <span className="flex h-3 items-end gap-[2px]" aria-hidden="true">
      {[0, 1, 2, 3].map((b) => (
        <span
          key={b}
          className="h-full w-[2px] origin-bottom animate-bars rounded-full bg-amber-glow"
          style={{ animationDelay: `${b * 120}ms` }}
        />
      ))}
    </span>
  );
}

export default function MessageBubble({ message, isStreaming = false }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const citations = message.citations ?? [];
  const tickers = isUser ? new Set<string>() : detectTickers(message.content, citations);

  // The user's question reads as the headline of a research note.
  if (isUser) {
    return (
      <div className="animate-rise mt-14 first:mt-0">
        <p className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.22em] text-paper-mute">
          <span className="text-amber-glow">›</span> You asked
        </p>
        <p className="mt-1.5 whitespace-pre-wrap font-display text-[26px] leading-[1.15] text-paper md:text-[30px]">
          {message.content}
        </p>
      </div>
    );
  }

  const waiting = isStreaming && message.content === "";

  return (
    <article className="animate-rise relative mt-5 border-l border-ink-600 pb-2 pl-6">
      {/* Timeline node — glows while the desk is writing */}
      <span
        className={`absolute -left-[5px] top-[3px] h-[9px] w-[9px] rotate-45 rounded-[2px] ${
          isStreaming ? "bg-amber-glow shadow-[0_0_12px_#ffb547] animate-pulse" : "bg-ink-600"
        }`}
        aria-hidden="true"
      />

      <p className="mb-3 flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.22em] text-paper-mute">
        <span className="text-paper-dim">Desk</span>
        <span>·</span>
        {isStreaming ? (
          <span className="flex items-center gap-2 text-amber-glow">
            <Bars />
            {waiting
              ? citations.length > 0
                ? `reading ${citations.length} source${citations.length === 1 ? "" : "s"}`
                : "pulling sources"
              : "writing"}
          </span>
        ) : (
          <span>memo</span>
        )}
      </p>

      {/* Grounded report visuals — every number from report data, never the LLM */}
      {message.insights && <InsightsPanel insights={message.insights} />}

      {/* Live quote card — shown above the text body (02-02) */}
      {message.quote && <QuoteCard quote={message.quote} />}

      {/*
        StreamingMarkdown handles debounced incremental rendering (smooth token
        streaming, flush on completion).
        T-06-01: StreamingMarkdown uses no rehype-raw, no dangerouslySetInnerHTML.
      */}
      {waiting ? (
        <div className="space-y-2.5 py-1" aria-label="Waiting for response">
          {["w-11/12", "w-9/12", "w-10/12"].map((w) => (
            <div key={w} className={`h-3 ${w} animate-pulse rounded bg-ink-800`} />
          ))}
        </div>
      ) : (
        <StreamingMarkdown content={message.content} streaming={isStreaming} tickers={tickers} />
      )}

      {/* Citations */}
      {citations.length > 0 && <Citations citations={citations} />}
    </article>
  );
}
