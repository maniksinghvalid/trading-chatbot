"use client";

/**
 * StreamingMarkdown.tsx — debounced incremental markdown rendering.
 *
 * Wraps the safe ReactMarkdown config from MessageBubble (anchor/code overrides,
 * NO rehype-raw — T-06-01) and debounces re-parsing of streaming content so that
 * rapid token updates don't thrash the markdown parser on every keystroke.
 *
 * Debounce strategy:
 *   - While content is actively streaming, re-parse is deferred by DEBOUNCE_MS (80ms).
 *   - On stream completion (streaming=false), flush immediately so the final
 *     rendered text equals the full streamed content (no dropped trailing tokens).
 *
 * The debounce is hand-rolled (no new npm dependency) per environment_notes constraint
 * (T-02-06-SC: reuses existing react-markdown; no new deps for a debounce util).
 *
 * Security (T-06-01): rehype-raw is NOT used. dangerouslySetInnerHTML is NEVER used.
 * LLM output cannot inject executable HTML/JS into the DOM.
 */

import { Children, useEffect, useRef, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import TickerChip from "./TickerChip";

/** Delay in milliseconds before committing a streaming content update to the parser. */
const DEBOUNCE_MS = 80;

interface StreamingMarkdownProps {
  /** The (potentially partial) markdown content to render. */
  content: string;
  /**
   * Set to true while the parent is actively receiving tokens.
   * When false the current content is flushed immediately, guaranteeing
   * the final render equals the full streamed text.
   */
  streaming: boolean;
  /**
   * Optional set of ticker symbols to wrap in TickerChip inside paragraph nodes.
   * Passed through to the p-component override. If empty, no chips are injected.
   */
  tickers?: Set<string>;
}

/**
 * Split plain text into segments, wrapping detected ticker symbols in TickerChip
 * and "[n]" citation markers in a small index badge (matches the source tiles).
 * Plain strings only — no raw HTML (T-06-01).
 */
function enhanceText(text: string, tickers: Set<string>): ReactNode[] {
  const alts = [...tickers].sort((a, b) => b.length - a.length).map((t) => `\\b${t}\\b`);
  alts.push("\\[\\d+\\]");
  // split() with one capture group puts the matches at odd indexes.
  return text.split(new RegExp(`(${alts.join("|")})`, "g")).map((part, i) => {
    if (i % 2 === 0) return part;
    if (tickers.has(part)) return <TickerChip key={i} ticker={part} />;
    return (
      <span
        key={i}
        className="mx-0.5 inline-grid h-[1.4em] min-w-[1.4em] place-items-center rounded-[5px] border border-ink-600 bg-ink-800 px-1 align-[0.12em] font-mono text-[0.68em] leading-none text-paper-dim"
        aria-label={`Source ${part.slice(1, -1)}`}
      >
        {part.slice(1, -1)}
      </span>
    );
  });
}

/** Apply enhanceText to every direct string child of a markdown node. */
function enhance(children: ReactNode, tickers: Set<string>): ReactNode {
  return Children.map(children, (child) =>
    typeof child === "string" ? enhanceText(child, tickers) : child
  );
}

export default function StreamingMarkdown({
  content,
  streaming,
  tickers = new Set(),
}: StreamingMarkdownProps) {
  // displayedContent is what actually gets passed to ReactMarkdown.
  // It lags behind `content` by up to DEBOUNCE_MS while streaming is active,
  // then is flushed immediately when streaming stops.
  const [displayedContent, setDisplayedContent] = useState(content);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    // Clear any in-flight debounce timer
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }

    if (!streaming) {
      // Stream completed — flush immediately to guarantee no trailing tokens are lost
      setDisplayedContent(content);
    } else {
      // Still streaming — defer the markdown re-parse by DEBOUNCE_MS
      timerRef.current = setTimeout(() => {
        setDisplayedContent(content);
        timerRef.current = null;
      }, DEBOUNCE_MS);
    }

    return () => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
      }
    };
  }, [content, streaming]);

  return (
    <div
      className={`break-words text-[15px] leading-7 text-paper/90 ${streaming ? "md-streaming" : ""}`}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // Headings — editorial serif for h1/h2, amber eyebrow for h3
          h1: ({ children }) => (
            <h1 className="mb-3 mt-7 font-display text-3xl leading-tight text-paper first:mt-0">
              {children}
            </h1>
          ),
          h2: ({ children }) => (
            <h2 className="mb-2.5 mt-7 font-display text-[26px] leading-tight text-paper first:mt-0">
              {children}
            </h2>
          ),
          h3: ({ children }) => (
            <h3 className="mb-2 mt-6 text-[12px] font-semibold uppercase tracking-[0.14em] text-amber-glow/90 first:mt-0">
              {children}
            </h3>
          ),
          ul: ({ children }) => (
            <ul className="my-3 list-disc space-y-1.5 pl-5 marker:text-amber-glow/60">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="my-3 list-decimal space-y-1.5 pl-6 marker:font-mono marker:text-[0.85em] marker:text-amber-glow/80">
              {children}
            </ol>
          ),
          li: ({ children }) => <li className="pl-1 leading-7">{enhance(children, tickers)}</li>,
          strong: ({ children }) => <strong className="font-semibold text-paper">{children}</strong>,
          hr: () => <hr className="my-6 border-dashed border-ink-600" />,
          blockquote: ({ children }) => (
            <blockquote className="my-4 border-l-2 border-amber-glow/50 pl-4 font-display text-xl italic leading-snug text-paper-dim">
              {children}
            </blockquote>
          ),
          // GFM tables
          table: ({ children }) => (
            <div className="my-4 overflow-x-auto rounded-xl border border-ink-700">
              <table className="w-full border-collapse text-[13px] tabular-nums">{children}</table>
            </div>
          ),
          th: ({ children }) => (
            <th className="bg-ink-850 px-3 py-2 text-left font-mono text-[10px] font-semibold uppercase tracking-[0.14em] text-paper-dim">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="border-t border-ink-700 px-3 py-2 align-top">{enhance(children, tickers)}</td>
          ),
          // Override anchor to open in new tab safely (T-06-01)
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-amber-glow underline decoration-amber-glow/40 underline-offset-2 hover:decoration-amber-glow"
            >
              {children}
            </a>
          ),
          // Override code blocks for consistent styling
          code: ({ className, children, ...props }) => {
            const isInline = !className;
            return isInline ? (
              <code
                className="rounded-md border border-ink-700 bg-ink-800 px-1.5 py-0.5 font-mono text-[0.85em] text-amber-glow/90"
                {...props}
              >
                {children}
              </code>
            ) : (
              <code
                className={`my-3 block overflow-x-auto rounded-xl border border-ink-700 bg-ink-900 p-4 font-mono text-xs ${className ?? ""}`}
                {...props}
              >
                {children}
              </code>
            );
          },
          // Paragraphs get ticker chips + citation badges. Plain text only (T-06-01).
          p: ({ children }) => (
            <p className="my-3 first:mt-0 last:mb-0">{enhance(children, tickers)}</p>
          ),
        }}
      >
        {displayedContent}
      </ReactMarkdown>
    </div>
  );
}
