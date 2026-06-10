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

import { useEffect, useRef, useState } from "react";
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
 * Split plain text into segments wrapping detected ticker symbols in TickerChip.
 * Identical helper to the one in MessageBubble — duplicated here so StreamingMarkdown
 * is a self-contained component with no cross-component dependency.
 */
function renderWithTickerChips(
  text: string,
  tickers: Set<string>
): React.ReactNode[] {
  if (tickers.size === 0) return [text];
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
    <div className="text-sm leading-relaxed break-words">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // Headings — explicit spacing/size since @tailwindcss/typography isn't installed
          h1: ({ children }) => (
            <h1 className="text-lg font-bold text-white mt-4 mb-2 first:mt-0">{children}</h1>
          ),
          h2: ({ children }) => (
            <h2 className="text-base font-bold text-white mt-4 mb-2 first:mt-0">{children}</h2>
          ),
          h3: ({ children }) => (
            <h3 className="text-sm font-semibold text-gray-100 mt-3 mb-1.5 first:mt-0">{children}</h3>
          ),
          // Lists — restore markers + vertical rhythm
          ul: ({ children }) => (
            <ul className="list-disc pl-5 my-2 space-y-1">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="list-decimal pl-5 my-2 space-y-1">{children}</ol>
          ),
          li: ({ children }) => <li className="leading-relaxed">{children}</li>,
          strong: ({ children }) => (
            <strong className="font-semibold text-white">{children}</strong>
          ),
          hr: () => <hr className="my-3 border-gray-700" />,
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 border-gray-600 pl-3 my-2 text-gray-300 italic">
              {children}
            </blockquote>
          ),
          // GFM tables
          table: ({ children }) => (
            <div className="my-2 overflow-x-auto">
              <table className="w-full text-xs border-collapse">{children}</table>
            </div>
          ),
          th: ({ children }) => (
            <th className="border border-gray-700 px-2 py-1 text-left font-semibold bg-gray-900/60">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="border border-gray-700 px-2 py-1 align-top">{children}</td>
          ),
          // Override anchor to open in new tab safely (T-06-01)
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
          // Override code blocks for consistent styling
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
          // Override paragraph to inject TickerChips for detected tickers.
          // Plain text strings are split by the ticker regex; no raw HTML is used (T-06-01).
          p: ({ children }) => {
            if (tickers.size === 0) {
              return <p className="my-2 leading-relaxed first:mt-0 last:mb-0">{children}</p>;
            }
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
            return <p className="my-2 leading-relaxed first:mt-0 last:mb-0">{enhanced}</p>;
          },
        }}
      >
        {displayedContent || "■"}
      </ReactMarkdown>
    </div>
  );
}
