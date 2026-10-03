"use client";

/**
 * page.tsx — home page with two-pane "Night Desk" layout.
 *
 * Layout:
 *   ┌──────────────┬────────────────────────────────────┐
 *   │  brand       │  status bar · AuthButton            │
 *   │  + New       ├────────────────────────────────────┤
 *   │  SessionList │  ChatWindow                         │
 *   │  disclaimer  │  (transcript + composer)            │
 *   └──────────────┴────────────────────────────────────┘
 *
 * Clicking a session in the sidebar calls onSelectSession, which sets
 * selectedSessionId + selectedMessages; these are passed as props to
 * ChatWindow so it restores the full history (POLISH-01 slice 11).
 *
 * SessionList also receives the activeSessionId for visual highlighting.
 *
 * refreshTrigger (POLISH-01 / gap-closure 02-09):
 *   A counter incremented in handleSessionChange whenever ChatWindow signals a
 *   *new* session_id (i.e. the backend created a new conversation on the first
 *   message).  Passing it to SessionList causes the sidebar to re-fetch so the
 *   new entry appears without a manual page reload.
 *
 * chatKey: "New session" bumps it so ChatWindow remounts with empty state and
 * no session_id — the backend then mints a fresh conversation on first send.
 */

import { useState } from "react";
import ChatWindow from "@/components/ChatWindow";
import SessionList from "@/components/SessionList";
import AuthButton from "@/components/AuthButton";
import BrandMark from "@/components/BrandMark";
import type { Message } from "@/lib/types";

export default function Home() {
  const [activeSessionId, setActiveSessionId] = useState<string | undefined>(undefined);
  const [restoredMessages, setRestoredMessages] = useState<Message[] | undefined>(undefined);
  const [restoredSessionId, setRestoredSessionId] = useState<string | undefined>(undefined);
  /**
   * Incrementing counter passed to SessionList as `refreshTrigger`.
   * Incremented whenever the active session changes to a NEW id — the first
   * message of a new conversation — so the sidebar re-fetches the session list.
   */
  const [refreshTrigger, setRefreshTrigger] = useState(0);
  const [chatKey, setChatKey] = useState(0);

  function handleSelectSession(sessionId: string, messages: Message[]) {
    setRestoredSessionId(sessionId);
    setRestoredMessages(messages);
    setActiveSessionId(sessionId);
    // User clicked an existing session; no new session was created, so we do
    // NOT increment refreshTrigger here — that would cause an unnecessary fetch.
  }

  function handleSessionChange(sessionId: string) {
    // Called by ChatWindow whenever the active session_id changes.
    // If the session_id is genuinely new (not the same as the current active),
    // increment refreshTrigger so SessionList re-fetches and surfaces the entry.
    if (sessionId !== activeSessionId) {
      setRefreshTrigger((prev) => prev + 1);
    }
    setActiveSessionId(sessionId);
  }

  function handleNewSession() {
    setRestoredMessages(undefined);
    setRestoredSessionId(undefined);
    setActiveSessionId(undefined);
    setChatKey((k) => k + 1);
  }

  return (
    <main className="flex h-dvh overflow-hidden desk-backdrop">
      {/* ── Sidebar ─────────────────────────────────────────────── */}
      <aside className="hidden md:flex w-72 flex-shrink-0 flex-col border-r border-ink-700/80 bg-ink-950/70 backdrop-blur-xl">
        <div className="flex items-center gap-3 px-5 pt-5 pb-4">
          <BrandMark />
          <div className="leading-none">
            <p className="font-display text-[22px] text-paper">
              Night <span className="italic text-amber-glow">Desk</span>
            </p>
            <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.22em] text-paper-mute">
              trading research
            </p>
          </div>
        </div>

        <div className="px-4 pb-3">
          <button
            type="button"
            onClick={handleNewSession}
            className="group flex w-full items-center gap-2 rounded-xl border border-amber-glow/30 bg-amber-glow/[0.06] px-3.5 py-2.5 text-sm font-medium text-amber-glow transition hover:border-amber-glow/60 hover:bg-amber-glow/10"
          >
            <span className="grid h-5 w-5 place-items-center rounded-md bg-amber-glow text-ink-950 text-base leading-none transition group-hover:rotate-90">
              +
            </span>
            New session
          </button>
        </div>

        <SessionList
          onSelectSession={handleSelectSession}
          activeSessionId={activeSessionId}
          refreshTrigger={refreshTrigger}
        />

        <p className="border-t border-ink-700/80 px-5 py-4 text-[11px] leading-relaxed text-paper-mute">
          Educational research only. Not financial advice — verify before you trade.
        </p>
      </aside>

      {/* ── Main column ─────────────────────────────────────────── */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex flex-shrink-0 items-center gap-3 border-b border-ink-700/60 bg-ink-950/40 px-4 py-3 backdrop-blur-xl md:px-6">
          <div className="flex items-center gap-2 md:hidden">
            <BrandMark className="h-7 w-7" />
            <span className="font-display text-lg">
              Night <span className="italic text-amber-glow">Desk</span>
            </span>
          </div>
          <div className="hidden items-center gap-2 font-mono text-[10px] uppercase tracking-[0.18em] text-paper-mute sm:flex">
            <span className="flex items-center gap-1.5 rounded-full border border-ink-700 bg-ink-900/70 px-2.5 py-1">
              <span className="relative flex h-1.5 w-1.5">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-gain opacity-60" />
                <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-gain" />
              </span>
              desk online
            </span>
            <span className="rounded-full border border-ink-700 bg-ink-900/70 px-2.5 py-1">pinecone rag</span>
            <span className="rounded-full border border-ink-700 bg-ink-900/70 px-2.5 py-1">sse stream</span>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              onClick={handleNewSession}
              className="rounded-lg border border-ink-600 px-2.5 py-1 text-xs text-paper-dim md:hidden"
            >
              + New
            </button>
            <AuthButton />
          </div>
        </header>

        <ChatWindow
          key={chatKey}
          onSessionChange={handleSessionChange}
          initialMessages={restoredMessages}
          initialSessionId={restoredSessionId}
        />
      </div>
    </main>
  );
}
