"use client";

/**
 * ChatWindow.tsx — streaming chat UI component.
 *
 * Handles SSE event flow from the backend /chat/stream endpoint:
 *   event=session   → store sessionId for conversation continuity
 *   event=citations → attach citations to the current assistant message
 *   event=token     → accumulate into the current assistant message content
 *   event=done      → stop streaming, set streaming=false
 *   event=error     → render error message, stop streaming
 *
 * Session continuity: sessionId is kept in state across sends so every
 * follow-up message continues the same conversation (coreference resolution
 * in the backend uses ticker_scope from prior turns).
 */

import { useRef, useEffect, useState, FormEvent } from "react";
import { streamChat } from "@/lib/api";
import type { Citation, Message } from "@/lib/types";
import MessageBubble from "./MessageBubble";

export default function ChatWindow() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  // Optional ticker scope hint. Sent on each turn; the backend persists it as
  // ticker_scope so a no-ticker follow-up ("what about its risks?") inherits it.
  const [ticker, setTicker] = useState("");
  const [sessionId, setSessionId] = useState<string | undefined>(undefined);
  const [streaming, setStreaming] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

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
  async function send(e?: FormEvent) {
    e?.preventDefault();
    const text = input.trim();
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
    <div className="flex flex-col h-full" style={{ minHeight: "calc(100vh - 57px)" }}>
      {/* Message list — scrollable area */}
      <div className="flex-1 overflow-y-auto px-4 py-4 chat-scroll">
        {messages.length === 0 && (
          <div className="flex items-center justify-center h-full text-gray-500 text-sm">
            <div className="text-center space-y-2">
              <p className="text-gray-400 font-medium">Trading Research Chatbot</p>
              <p>Ask a question about a ticker, e.g.</p>
              <p className="text-blue-400 italic">"Bull case for AAPL"</p>
              <p className="text-gray-600 text-xs mt-4">
                Enter a ticker (optional) and ask a question; follow-ups remember
                the last ticker. Auto-extraction is Phase 2.
              </p>
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <MessageBubble key={i} message={msg} />
        ))}

        {/* Streaming indicator — shown only while the assistant is responding */}
        {streaming && (
          <div className="flex justify-start mb-4 px-1">
            <span className="text-xs text-gray-500 animate-pulse">
              Streaming response...
            </span>
          </div>
        )}

        {/* Invisible anchor for auto-scroll */}
        <div ref={bottomRef} />
      </div>

      {/* Input area */}
      <form
        onSubmit={send}
        className="border-t border-gray-800 px-4 py-3 flex gap-2 bg-gray-950"
      >
        {/* Ticker scope hint — optional. Kept across sends so follow-ups inherit it. */}
        <input
          type="text"
          value={ticker}
          onChange={(e) => setTicker(e.target.value.toUpperCase().trim())}
          placeholder="Ticker"
          maxLength={10}
          disabled={streaming}
          aria-label="Ticker symbol (optional)"
          className="w-24 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-600 focus:border-transparent disabled:opacity-50 disabled:cursor-not-allowed"
          autoComplete="off"
        />
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={streaming ? "Waiting for response…" : "Ask about a ticker…"}
          disabled={streaming}
          className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-600 focus:border-transparent disabled:opacity-50 disabled:cursor-not-allowed"
          autoComplete="off"
          autoFocus
        />
        <button
          type="submit"
          disabled={streaming || !input.trim()}
          className="bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:cursor-not-allowed text-white font-medium rounded-lg px-4 py-2 text-sm transition-colors"
        >
          {streaming ? "…" : "Send"}
        </button>
      </form>
    </div>
  );
}
