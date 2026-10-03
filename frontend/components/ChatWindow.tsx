"use client";

/**
 * ChatWindow.tsx — streaming chat UI component.
 *
 * Handles SSE event flow from the backend /chat/stream endpoint:
 *   event=session   → store sessionId for conversation continuity
 *   event=citations → attach citations to the current assistant message
 *   event=quote     → attach live market-data quote to the current assistant message (02-02)
 *   event=token     → accumulate into the current assistant message content
 *   event=done      → stop streaming, set streaming=false
 *   event=error     → render error message, stop streaming
 *
 * Session continuity: sessionId is kept in state across sends so every
 * follow-up message continues the same conversation (coreference resolution
 * in the backend uses ticker_scope from prior turns).
 *
 * Session restore (POLISH-01): accepts an optional initialMessages/initialSessionId
 * pair so the SessionList sidebar can load a prior session's full history.
 */

import { useRef, useEffect, useState, FormEvent } from "react";
import { streamChat } from "@/lib/api";
import type { Citation, Message, Quote } from "@/lib/types";
import MessageBubble from "./MessageBubble";

/** Starter prompts for the empty state. Clicking one sends it immediately. */
const SUGGESTIONS = [
  { tag: "MARA", kind: "Analysis", prompt: "Summarize the latest full analysis on MARA" },
  { tag: "MARA", kind: "Options", prompt: "What do the recent options reports say about MARA?" },
  { tag: "MARA", kind: "Live quote", prompt: "What is MARA's price right now?" },
  { tag: "NVDA", kind: "Thesis", prompt: "Bull case vs. bear case for NVDA" },
];

interface ChatWindowProps {
  /**
   * Called whenever the active session_id changes (new session or restored session),
   * so the parent can pass it down to SessionList for visual highlighting.
   */
  onSessionChange?: (sessionId: string) => void;
  /**
   * Pre-loaded messages to restore when the user clicks a session in the sidebar.
   * Passing a new array replaces the current messages state.
   */
  initialMessages?: Message[];
  /**
   * Pre-loaded session UUID to continue when restoring a sidebar session.
   */
  initialSessionId?: string;
}

export default function ChatWindow({
  onSessionChange,
  initialMessages,
  initialSessionId,
}: ChatWindowProps) {
  const [messages, setMessages] = useState<Message[]>(initialMessages ?? []);
  const [input, setInput] = useState("");
  // Optional ticker scope hint. Sent on each turn; the backend persists it as
  // ticker_scope so a no-ticker follow-up ("what about its risks?") inherits it.
  const [ticker, setTicker] = useState("");
  const [sessionId, setSessionId] = useState<string | undefined>(initialSessionId);
  const [streaming, setStreaming] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // When the parent loads a new session (sidebar click), replace messages + sessionId
  useEffect(() => {
    if (initialMessages !== undefined) {
      setMessages(initialMessages);
    }
  }, [initialMessages]);

  useEffect(() => {
    if (initialSessionId !== undefined) {
      setSessionId(initialSessionId);
    }
  }, [initialSessionId]);

  // Auto-scroll to the bottom whenever messages update
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  /** Append a new message to the messages array. */
  function appendMessage(msg: Message) {
    setMessages((prev) => [...prev, msg]);
  }

  /**
   * Update the last message in the array.
   * Used to accumulate streaming tokens into the assistant bubble.
   */
  function updateLastMessage(updater: (prev: Message) => Message) {
    setMessages((prev) => {
      if (prev.length === 0) return prev;
      const last = updater(prev[prev.length - 1]);
      return [...prev.slice(0, -1), last];
    });
  }

  /**
   * Send the current input to the backend and stream the response.
   * Keeps sessionId across calls for multi-turn continuity.
   */
  async function send(e?: FormEvent, prompt?: string) {
    e?.preventDefault();
    const text = (prompt ?? input).trim();
    if (!text || streaming) return;

    setInput("");
    setStreaming(true);

    // Append user message immediately for responsiveness
    appendMessage({ role: "user", content: text });

    // Append an empty assistant message — tokens will accumulate into it
    appendMessage({ role: "assistant", content: "", citations: [] });

    // Pass the ticker as the optional 3rd arg so the backend scopes retrieval and
    // persists ticker_scope. undefined when blank preserves the optional behavior.
    try {
      for await (const event of streamChat(text, sessionId, ticker.trim() || undefined)) {
        switch (event.event) {
          case "session":
            // Store session ID so follow-up messages continue the conversation
            setSessionId(event.data);
            onSessionChange?.(event.data);
            break;

          case "citations": {
            // Citations arrive once up front, before any token
            let parsed: Citation[] = [];
            try {
              parsed = JSON.parse(event.data) as Citation[];
            } catch {
              // Malformed JSON — degrade gracefully with empty citations
              parsed = [];
            }
            updateLastMessage((prev) => ({ ...prev, citations: parsed }));
            break;
          }

          case "quote": {
            // Live market-data quote (price-intent only, from 02-02)
            let parsedQuote: Quote | undefined;
            try {
              parsedQuote = JSON.parse(event.data) as Quote;
            } catch {
              parsedQuote = undefined;
            }
            if (parsedQuote) {
              updateLastMessage((prev) => ({ ...prev, quote: parsedQuote }));
            }
            break;
          }

          case "token":
            // Accumulate token into the current assistant message content
            updateLastMessage((prev) => ({
              ...prev,
              content: prev.content + event.data,
            }));
            break;

          case "done":
            // Stream complete — the for-await loop exits naturally after this
            break;

          case "error":
            // Backend emitted a safe error message; render it as the response
            updateLastMessage((prev) => ({
              ...prev,
              content: event.data || "An error occurred. Please try again.",
            }));
            break;

          default:
            // Unknown event type — ignore silently
            break;
        }
      }
    } catch (err) {
      // Network / parse error — update the assistant bubble with a user-safe message
      updateLastMessage((prev) => ({
        ...prev,
        content:
          "Could not reach the server. Please check that the backend is running on " +
          (process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000") +
          " and try again.",
      }));
    } finally {
      setStreaming(false);
      inputRef.current?.focus();
    }
  }

  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      {/* Transcript — scrollable area */}
      <div className="chat-scroll flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-3xl px-5 pb-40 pt-10 md:px-8">
          {messages.length === 0 && (
            <section className="animate-rise pt-[6vh]">
              <p className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.25em] text-amber-glow">
                <span className="h-px w-8 bg-amber-glow/60" />
                after-hours research desk
              </p>
              <h1 className="mt-5 font-display text-5xl leading-[1.02] text-paper md:text-7xl">
                Research,
                <br />
                <span className="italic text-amber-glow">on the record.</span>
              </h1>
              <p className="mt-5 max-w-xl text-[15px] leading-relaxed text-paper-dim">
                Ask about any ticker in your report library. Every answer is grounded in
                your <span className="font-mono text-[13px] text-paper">TRADE-*</span> reports
                and cites its sources — follow-ups remember the ticker you were on.
              </p>

              <div className="mt-10 grid gap-3 sm:grid-cols-2">
                {SUGGESTIONS.map((s, i) => (
                  <button
                    key={s.prompt}
                    type="button"
                    onClick={() => send(undefined, s.prompt)}
                    style={{ animationDelay: `${120 + i * 70}ms` }}
                    className="group animate-rise relative overflow-hidden rounded-2xl border border-ink-700 bg-ink-900/60 p-4 text-left transition hover:-translate-y-0.5 hover:border-amber-glow/40 hover:bg-ink-850"
                  >
                    <span className="flex items-center justify-between font-mono text-[10px] uppercase tracking-[0.18em]">
                      <span className="text-amber-glow">${s.tag}</span>
                      <span className="text-paper-mute">{s.kind}</span>
                    </span>
                    <span className="mt-3 block text-sm leading-snug text-paper">{s.prompt}</span>
                    <span className="absolute bottom-3 right-4 translate-x-2 text-amber-glow opacity-0 transition group-hover:translate-x-0 group-hover:opacity-100">
                      →
                    </span>
                  </button>
                ))}
              </div>
            </section>
          )}

          {messages.map((msg, i) => (
            <MessageBubble
              key={i}
              message={msg}
              // The last message is the one being streamed when streaming=true
              isStreaming={streaming && i === messages.length - 1}
            />
          ))}

          {/* Invisible anchor for auto-scroll */}
          <div ref={bottomRef} />
        </div>
      </div>

      {/* Composer — floating command bar */}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-ink-950 via-ink-950/90 to-transparent pt-16">
        <form
          onSubmit={send}
          className="pointer-events-auto mx-auto w-full max-w-3xl px-4 pb-4 md:px-8"
        >
          <div className="flex items-end gap-2 rounded-2xl border border-ink-600 bg-ink-900/90 p-2 shadow-[0_24px_60px_-20px_rgba(0,0,0,0.9)] backdrop-blur-xl transition focus-within:border-amber-glow/50 focus-within:shadow-[0_0_0_4px_rgba(255,181,71,0.08),0_24px_60px_-20px_rgba(0,0,0,0.9)]">
            {/* Ticker scope hint — optional. Kept across sends so follow-ups inherit it. */}
            <label className="flex h-10 flex-shrink-0 items-center rounded-xl border border-ink-700 bg-ink-850 pl-2.5 font-mono text-sm focus-within:border-amber-glow/50">
              <span className={ticker ? "text-amber-glow" : "text-paper-mute"}>$</span>
              <input
                type="text"
                value={ticker}
                onChange={(e) => setTicker(e.target.value.toUpperCase().trim())}
                placeholder="TICKER"
                maxLength={10}
                disabled={streaming}
                aria-label="Ticker symbol (optional)"
                className="w-[4.5rem] bg-transparent px-1.5 py-2 uppercase text-amber-glow placeholder:text-[11px] placeholder:tracking-widest placeholder:text-paper-mute focus:outline-none disabled:opacity-50"
                autoComplete="off"
              />
            </label>
            <textarea
              ref={inputRef}
              rows={1}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                // Enter sends; Shift+Enter inserts a newline; ignore IME composition.
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  send();
                }
              }}
              placeholder={streaming ? "The desk is writing…" : "Ask the desk about a ticker…"}
              disabled={streaming}
              aria-label="Message"
              className="composer-input max-h-40 min-h-10 flex-1 resize-none bg-transparent px-2 py-2.5 text-[15px] leading-5 text-paper placeholder:text-paper-mute focus:outline-none disabled:opacity-60"
              autoComplete="off"
              autoFocus
            />
            <button
              type="submit"
              disabled={streaming || !input.trim()}
              aria-label="Send"
              className="grid h-10 w-10 flex-shrink-0 place-items-center rounded-xl bg-amber-glow text-ink-950 transition hover:brightness-110 disabled:bg-ink-700 disabled:text-paper-mute"
            >
              {streaming ? (
                <span className="flex h-4 items-end gap-[3px]" aria-hidden="true">
                  {[0, 1, 2].map((b) => (
                    <span
                      key={b}
                      className="h-full w-[3px] origin-bottom animate-bars rounded-full bg-current"
                      style={{ animationDelay: `${b * 150}ms` }}
                    />
                  ))}
                </span>
              ) : (
                <svg viewBox="0 0 20 20" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden="true">
                  <path d="M10 16V4M4.5 9.5 10 4l5.5 5.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              )}
            </button>
          </div>
          <p className="mt-2 text-center font-mono text-[10px] tracking-wide text-paper-mute">
            enter to send · shift+enter for a new line · educational research, not financial advice
          </p>
        </form>
      </div>
    </div>
  );
}
