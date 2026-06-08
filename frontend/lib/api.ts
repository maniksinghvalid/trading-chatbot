/**
 * api.ts — Async generator client for the backend /chat/stream SSE endpoint.
 *
 * streamChat(message, sessionId?, ticker?) POSTs to the backend and yields
 * parsed SSE events {event, data} as they arrive.
 *
 * SSE wire format (per 01-CONTEXT.md locked order). The backend uses sse-starlette,
 * which emits CRLF-delimited events — `\r\n` field lines, `\r\n\r\n` event separators:
 *   event: session\r\ndata: <uuid>\r\n\r\n
 *   event: citations\r\ndata: <JSON Citation[]>\r\n\r\n
 *   event: token\r\ndata: <partial token>\r\n\r\n   (repeated)
 *   event: done\r\ndata: \r\n\r\n
 * The parser tolerates BOTH CRLF and bare-LF wire formats (see the split regexes).
 *
 * Security: This module never calls dangerouslySetInnerHTML or renders raw HTML.
 * The backend URL comes from NEXT_PUBLIC_API_BASE (public env var — safe to expose).
 */

import type { ChatRequest, StreamEvent } from "./types";

/** Backend base URL, defaulting to local FastAPI dev server. */
const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

/**
 * Parse a single SSE block (the text between two blank lines) into a StreamEvent.
 *
 * A block looks like:
 *   "event: session\ndata: abc-123"
 *
 * Returns null if the block is empty or missing a data line.
 */
export function parseSSEBlock(block: string): StreamEvent | null {
  // Split on \r?\n so each field line is parsed whether the wire used \r\n (CRLF,
  // as sse-starlette emits) or bare \n. This strips any trailing \r, so data:
  // payloads carry no \r and JSON.parse of the citations payload succeeds.
  const lines = block.split(/\r?\n/);
  let event = "message";
  let data = "";

  for (const line of lines) {
    if (line.startsWith("event:")) {
      // Strip "event:" prefix and exactly one leading space (if present)
      event = line.slice(6).replace(/^ /, "");
    } else if (line.startsWith("data:")) {
      // Strip "data:" prefix and exactly one leading space (if present)
      data = line.slice(5).replace(/^ /, "");
    }
    // Ignore comment lines (starting with ':') and id:/retry: lines
  }

  if (!event && data === "") return null;

  return { event, data };
}

/**
 * Async generator that streams chat responses from the backend /chat/stream endpoint.
 *
 * @param message  The user's question.
 * @param sessionId  Optional existing session UUID (for conversation continuity).
 * @param ticker   Optional UPPERCASE ticker to scope retrieval (e.g. "AAPL").
 *
 * Yields parsed SSE events in the order emitted by the backend:
 *   {event: "session", data: "<uuid>"}
 *   {event: "citations", data: "<JSON>"}
 *   {event: "token", data: "<partial>"}  (repeated)
 *   {event: "done", data: ""}
 *
 * Throws on non-2xx HTTP responses.
 */
export async function* streamChat(
  message: string,
  sessionId?: string,
  ticker?: string
): AsyncGenerator<StreamEvent> {
  const body: ChatRequest = {
    message,
    ...(sessionId ? { session_id: sessionId } : {}),
    ...(ticker ? { ticker } : {}),
  };

  const response = await fetch(`${API_BASE}/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    throw new Error(
      `Backend returned ${response.status}: ${response.statusText}`
    );
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error("Response body is not readable");
  }

  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      // Append the new chunk to our rolling buffer
      buffer += decoder.decode(value, { stream: true });

      // SSE events are delimited by a blank line. sse-starlette emits CRLF
      // (\r\n\r\n); tolerate bare-LF (\n\n) too for backward compatibility.
      const parts = buffer.split(/\r\n\r\n|\n\n/);

      // The last part may be an incomplete block — keep it in the buffer
      buffer = parts.pop() ?? "";

      for (const part of parts) {
        const trimmed = part.trim();
        if (!trimmed) continue;

        const event = parseSSEBlock(trimmed);
        if (event) {
          yield event;
          // Stop consuming after "done" — the stream is complete
          if (event.event === "done") {
            return;
          }
        }
      }
    }

    // Drain any remaining buffer after the stream closes
    if (buffer.trim()) {
      const event = parseSSEBlock(buffer.trim());
      if (event) yield event;
    }
  } finally {
    reader.releaseLock();
  }
}
