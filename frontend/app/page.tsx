"use client";

/**
 * page.tsx — home page with two-pane layout.
 *
 * Layout:
 *   ┌──────────────┬────────────────────────────────────┐
 *   │  SessionList │  ChatWindow                         │
 *   │  (sidebar)   │  (chat area)                        │
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
 */

import { useState } from "react";
import ChatWindow from "@/components/ChatWindow";
import SessionList from "@/components/SessionList";
import AuthButton from "@/components/AuthButton";
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

  return (
    <main className="flex min-h-screen flex-col">
      <header className="border-b border-gray-800 px-4 py-3 flex items-center gap-3 flex-shrink-0">
        <span className="text-lg font-semibold text-white">Trading Chatbot</span>
        <span className="text-xs text-gray-500 hidden sm:block">
          Pinecone RAG · SSE streaming
        </span>
        <AuthButton />
      </header>
      <div className="flex flex-1 overflow-hidden">
        <SessionList
          onSelectSession={handleSelectSession}
          activeSessionId={activeSessionId}
          refreshTrigger={refreshTrigger}
        />
        <div className="flex-1 flex flex-col min-w-0">
          <ChatWindow
            onSessionChange={handleSessionChange}
            initialMessages={restoredMessages}
            initialSessionId={restoredSessionId}
          />
        </div>
      </div>
    </main>
  );
}
