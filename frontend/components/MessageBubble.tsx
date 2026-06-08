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
 */

import ReactMarkdown from "react-markdown";
import type { Citation, Message } from "@/lib/types";

interface MessageBubbleProps {
  message: Message;
}

/**
 * Sources list rendered below assistant bubbles when citations are present.
 * Renders only fields emitted by the backend from real chunk metadata (T-06-03).
 */
function Sources({ citations }: { citations: Citation[] }) {
  if (!citations || citations.length === 0) return null;

  return (
    <div className="mt-3 pt-3 border-t border-gray-700">
      <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
        Sources
      </p>
      <ol className="space-y-1">
        {citations.map((c, i) => (
          <li key={`${c.source_path}-${i}`} className="text-xs text-gray-400">
            <span className="font-mono text-gray-500">[{i + 1}]</span>{" "}
            <span className="text-gray-300">{c.source_path}</span>
            <span className="text-gray-600"> &bull; </span>
            <span className="text-blue-400">{c.report_type}</span>
            <span className="text-gray-600"> &bull; </span>
            <span>{c.generated_date}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

export default function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";

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
            }}
          >
            {message.content || (isUser ? "" : "■")}
          </ReactMarkdown>
        </div>

        {/* Sources list — only rendered for assistant messages with citations */}
        {!isUser && message.citations && message.citations.length > 0 && (
          <Sources citations={message.citations} />
        )}
      </div>
    </div>
  );
}
