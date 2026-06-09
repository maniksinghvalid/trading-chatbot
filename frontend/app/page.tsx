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
 */

import { useState } from "react";
import ChatWindow from "@/components/ChatWindow";
import SessionList from "@/components/SessionList";
import type { Message } from "@/lib/types";

export default function Home() {
  const [activeSessionId, setActiveSessionId] = useState<string | undefined>(undefined);
  const [restoredMessages, setRestoredMessages] = useState<Message[] | undefined>(undefined);
  const [restoredSessionId, setRestoredSessionId] = useState<string | undefined>(undefined);

  function handleSelectSession(sessionId: string, messages: Message[]) {
    setRestoredSessionId(sessionId);
    setRestoredMessages(messages);
    setActiveSessionId(sessionId);
  }

  function handleSessionChange(sessionId: string) {
    setActiveSessionId(sessionId);
  }

  return (
    <main className="flex min-h-screen flex-col">
      <header className="border-b border-gray-800 px-4 py-3 flex items-center gap-3 flex-shrink-0">
        <span className="text-lg font-semibold text-white">Trading Chatbot</span>
        <span className="text-xs text-gray-500 hidden sm:block">
          Pinecone RAG · SSE streaming
        </span>
      </header>
      <div className="flex flex-1 overflow-hidden">
        <SessionList
          onSelectSession={handleSelectSession}
          activeSessionId={activeSessionId}
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
