/**
 * api.test.ts — Regression tests for the SSE wire parser in api.ts.
 *
 * The backend (sse-starlette) emits CRLF-delimited events: `\r\n` field lines,
 * `\r\n\r\n` event separators. The original parser split on `\n\n` / `\n`, so no
 * event parsed during streaming (empty bubble + infinite spinner). These tests
 * feed the exact CRLF bytes and prove the parser handles both CRLF and LF wire
 * formats, including a chunk boundary that splits mid-separator.
 *
 * Tests A/B drive streamChat with a mocked fetch ReadableStream (replays bytes
 * exactly as the wire would). Tests C/D call parseSSEBlock directly.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { streamChat, parseSSEBlock } from "./api";
import type { StreamEvent } from "./types";

/** Mock global.fetch to return a streaming Response built from the given chunks. */
function mockFetchStreaming(chunks: string[]) {
  const encoder = new TextEncoder();
  return vi.fn(async () => {
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const c of chunks) controller.enqueue(encoder.encode(c));
        controller.close();
      },
    });
    return new Response(stream, {
      status: 200,
      headers: { "Content-Type": "text/event-stream" },
    });
  });
}

/** Drive streamChat against a mocked stream and collect all yielded events. */
async function collect(chunks: string[]): Promise<StreamEvent[]> {
  vi.stubGlobal("fetch", mockFetchStreaming(chunks));
  const out: StreamEvent[] = [];
  for await (const ev of streamChat("hi")) out.push(ev);
  return out;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SSE CRLF wire parsing", () => {
  it("Test A — splits CRLF-delimited events into session/token/done in order", async () => {
    const wire =
      "event: session\r\ndata: abc-123\r\n\r\n" +
      "event: token\r\ndata: Hello\r\n\r\n" +
      "event: done\r\ndata: \r\n\r\n";
    const events = await collect([wire]);
    expect(events).toEqual([
      { event: "session", data: "abc-123" },
      { event: "token", data: "Hello" },
      { event: "done", data: "" },
    ]);
  });

  it("Test B — handles a chunk boundary that splits inside the \\r\\n\\r\\n separator", async () => {
    const full =
      "event: session\r\ndata: abc-123\r\n\r\n" +
      "event: token\r\ndata: Hello\r\n\r\n" +
      "event: done\r\ndata: \r\n\r\n";
    // Break the stream into two reader chunks mid-separator, after "Hello\r\n\r".
    const marker = "Hello\r\n\r";
    const splitAt = full.indexOf(marker) + marker.length;
    const events = await collect([full.slice(0, splitAt), full.slice(splitAt)]);
    expect(events).toEqual([
      { event: "session", data: "abc-123" },
      { event: "token", data: "Hello" },
      { event: "done", data: "" },
    ]);
  });

  it("Test C — LF-only block parses identically (backward compatibility)", () => {
    expect(parseSSEBlock("event: token\ndata: Hi")).toEqual({
      event: "token",
      data: "Hi",
    });
  });

  it("Test D — CRLF block yields data with no trailing \\r so JSON.parse succeeds", () => {
    const block = 'event: citations\r\ndata: [{"ticker":"MARA"}]';
    const ev = parseSSEBlock(block);
    expect(ev).toEqual({ event: "citations", data: '[{"ticker":"MARA"}]' });
    expect(() => JSON.parse(ev!.data)).not.toThrow();
  });

  it("Test E — multiple data: lines in one event rejoin with \\n (SSE multiline)", () => {
    // sse-starlette serialises a data field containing "\n\n## Heading" as three
    // consecutive `data:` lines. The parser MUST rejoin them with "\n" — otherwise
    // every newline inside a token is dropped and Markdown collapses to one line.
    const block = "event: token\r\ndata: \r\ndata: \r\ndata: ## Heading";
    const ev = parseSSEBlock(block);
    expect(ev).toEqual({ event: "token", data: "\n\n## Heading" });
  });

  it("Test F — streamChat preserves newlines across a multi-line token event", async () => {
    const wire =
      "event: token\r\ndata: - one\r\ndata: - two\r\n\r\n" +
      "event: done\r\ndata: \r\n\r\n";
    const events = await collect([wire]);
    expect(events[0]).toEqual({ event: "token", data: "- one\n- two" });
  });
});
