/**
 * types.ts — TypeScript mirrors of the backend Pydantic schemas.
 *
 * These match the locked contract in 01-CONTEXT.md / backend/src/schemas.py.
 * Do NOT rename fields without a coordinated backend migration.
 *
 * Models:
 *   Citation        — a single source chunk cited in a response
 *   ChatRequest     — user message payload (POST /chat/stream)
 *   ChatResponse    — non-streaming response shape (POST /chat)
 *   StreamEvent     — a parsed SSE event {event, data} from /chat/stream
 *   Message         — local UI message (role, content, citations, quote)
 *   Quote           — live market-data quote from the SSE quote event (02-02)
 *   SessionSummary  — summary entry returned by GET /sessions
 *   SessionTurn     — a single turn entry from GET /sessions/{id}
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

/**
 * Live market-data quote emitted as SSE event: quote (added in 02-02).
 * Shape mirrors market_data.quote() return dict from the backend.
 * ~15-min delayed (yfinance); every quote carries a timestamp and source label.
 */
export interface Quote {
  /** Latest price (numeric). */
  price: number;
  /** Day change percentage (positive = up, negative = down). */
  day_change_pct: number;
  /** Share volume for the trading day. */
  volume: number;
  /** ISO-8601 timestamp of when the backend fetched the quote. */
  timestamp: string;
  /** Data provider label, e.g. "yfinance". */
  source: string;
}

/**
 * A session entry returned by GET /sessions (list).
 * Mirrors the backend shape: {session_id, title}.
 */
export interface SessionSummary {
  /** UUID of the session. */
  session_id: string;
  /** Display title — typically the first user message of the session. */
  title: string;
}

/**
 * A single turn entry returned by GET /sessions/{session_id}.
 * Mirrors the backend shape: {role, content, created_at}.
 */
export interface SessionTurn {
  /** "user" or "assistant". */
  role: "user" | "assistant";
  /** Full message content. */
  content: string;
  /** ISO-8601 creation timestamp. */
  created_at: string;
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
 * Event order (locked per 01-CONTEXT.md + 02-02 additive extension):
 *   1. event="session"   data=<session_id UUID>
 *   2. event="citations" data=<JSON Citation[]>
 *   2a. event="quote"   data=<JSON Quote> (added in 02-02; only for price-intent questions)
 *   3. event="token"     data=<partial token string>  (repeated N times)
 *   4. event="done"      data=""
 *
 * Error path: event="error" then event="done" (no key/stack trace in data).
 */
export interface StreamEvent {
  event: "session" | "citations" | "quote" | "token" | "done" | "error" | string;
  data: string;
}

/** Local UI message (stored in ChatWindow state). */
export interface Message {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  /** Live market-data quote, if the backend emitted a quote event for this message. */
  quote?: Quote;
}
