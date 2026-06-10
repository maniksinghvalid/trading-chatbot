/**
 * api.ts — Async generator client for the backend /chat/stream SSE endpoint,
 * plus helpers for the session list/history endpoints.
 *
 * streamChat(message, sessionId?, ticker?) POSTs to the backend and yields
 * parsed SSE events {event, data} as they arrive.
 *
 * SSE wire format (per 01-CONTEXT.md locked order). The backend uses sse-starlette,
 * which emits CRLF-delimited events — `\r\n` field lines, `\r\n\r\n` event separators:
 *   event: session\r\ndata: <uuid>\r\n\r\n
 *   event: citations\r\ndata: <JSON Citation[]>\r\n\r\n
 *   event: quote\r\ndata: <JSON Quote>\r\n\r\n  (price-intent only, added 02-02)
 *   event: token\r\ndata: <partial token>\r\n\r\n   (repeated)
 *   event: done\r\ndata: \r\n\r\n
 * The parser tolerates BOTH CRLF and bare-LF wire formats (see the split regexes).
 *
 * Security: This module never calls dangerouslySetInnerHTML or renders raw HTML.
 * The backend URL comes from NEXT_PUBLIC_API_BASE (public env var — safe to expose).
 */

import type { ChatRequest, SessionSummary, SessionTurn, StreamEvent } from "./types";

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
  const dataLines: string[] = [];

  for (const line of lines) {
    if (line.startsWith("event:")) {
      // Strip "event:" prefix and exactly one leading space (if present)
      event = line.slice(6).replace(/^ /, "");
    } else if (line.startsWith("data:")) {
      // Strip "data:" prefix and exactly one leading space (if present).
      // Per the SSE spec, a single event's data field that contains newlines is
      // transmitted as MULTIPLE consecutive `data:` lines; the client MUST rejoin
      // them with "\n". Keeping only the last line (the previous bug) silently
      // dropped every newline inside a token, collapsing all Markdown structure
      // (headings, lists, blank lines) onto one line.
      dataLines.push(line.slice(5).replace(/^ /, ""));
    }
    // Ignore comment lines (starting with ':') and id:/retry: lines
  }

  const data = dataLines.join("\n");

  if (!event && dataLines.length === 0) return null;

  return { event, data };
}

/**
 * Read the JWT from localStorage (set by the auth callback handler).
 *
 * Returns an empty string when localStorage is unavailable (SSR context)
 * or when no token has been stored yet.  The caller adds the header only
 * when a non-empty token is returned.
 */
function getStoredToken(): string {
  if (typeof window === "undefined") return "";
  return localStorage.getItem("access_token") ?? "";
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
 * Throws on non-2xx HTTP responses (including 401 Unauthorized when no JWT
 * is stored or the stored JWT has expired).
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

  // Build request headers.  The Authorization header is added whenever a JWT
  // is present in localStorage (stored by the auth callback handler on login).
  const token = getStoredToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "text/event-stream",
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE}/chat/stream`, {
    method: "POST",
    headers,
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

/**
 * Fetch the list of sessions owned by the authenticated user.
 *
 * GET /sessions — returns [{session_id, title}, ...] filtered to the current JWT sub.
 * Attaches the Bearer token from localStorage (same pattern as streamChat).
 *
 * Throws on non-2xx HTTP responses (e.g. 401 when token is absent/expired).
 */
export async function fetchSessions(): Promise<SessionSummary[]> {
  const token = getStoredToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE}/sessions`, { headers });

  if (!response.ok) {
    throw new Error(
      `GET /sessions returned ${response.status}: ${response.statusText}`
    );
  }

  return (await response.json()) as SessionSummary[];
}

/**
 * Fetch the full turn history for a session.
 *
 * GET /sessions/{session_id} — returns [{role, content, created_at}, ...].
 * Attaches the Bearer token. Ownership is enforced by the backend (T-02-03-02).
 *
 * Throws on non-2xx responses.
 */
export async function fetchSessionTurns(sessionId: string): Promise<SessionTurn[]> {
  const token = getStoredToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE}/sessions/${encodeURIComponent(sessionId)}`, {
    headers,
  });

  if (!response.ok) {
    throw new Error(
      `GET /sessions/${sessionId} returned ${response.status}: ${response.statusText}`
    );
  }

  return (await response.json()) as SessionTurn[];
}
