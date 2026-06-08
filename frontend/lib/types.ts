/**
 * types.ts — TypeScript mirrors of the backend Pydantic schemas.
 *
 * These match the locked contract in 01-CONTEXT.md / backend/src/schemas.py.
 * Do NOT rename fields without a coordinated backend migration.
 *
 * Models:
 *   Citation      — a single source chunk cited in a response
 *   ChatRequest   — user message payload (POST /chat/stream)
 *   ChatResponse  — non-streaming response shape (POST /chat)
 *   StreamEvent   — a parsed SSE event {event, data} from /chat/stream
 *   Message       — local UI message (role, content, citations)
 */

/** Metadata for a single source chunk cited in a response. */
export interface Citation {
  /** Path / identifier of the originating trade report file. */
  source_path: string;
  /** Date the source report was generated (YYYYMMDD or ISO string). */
  generated_date: string;
  /** Ticker symbol from the record metadata. */
  ticker: string;
  /** Report type: ANALYSIS, TECHNICAL, OPTIONS, etc. */
  report_type: string;
}

/** Incoming chat request to the backend. */
export interface ChatRequest {
  /** The user's natural-language question. */
  message: string;
  /** Optional UPPERCASE ticker symbol scoping the retrieval (e.g. "AAPL"). */
  ticker?: string;
  /** Optional existing session UUID. Absent → backend mints a new uuid4. */
  session_id?: string;
}

/** Non-streaming response from POST /chat (used for type reference). */
export interface ChatResponse {
  /** The assistant's grounded answer with inline source citations. */
  message: string;
  /** List of Citation objects for every source chunk used. Empty on no-data path. */
  citations: Citation[];
  /** UUID identifying this conversation session. */
  session_id: string;
}

/**
 * A single parsed SSE event from POST /chat/stream.
 *
 * Event order (locked per 01-CONTEXT.md):
 *   1. event="session"   data=<session_id UUID>
 *   2. event="citations" data=<JSON Citation[]>
 *   3. event="token"     data=<partial token string>  (repeated N times)
 *   4. event="done"      data=""
 *
 * Error path: event="error" then event="done" (no key/stack trace in data).
 */
export interface StreamEvent {
  event: "session" | "citations" | "token" | "done" | "error" | string;
  data: string;
}

/** Local UI message (stored in ChatWindow state). */
export interface Message {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
}
