"use client";

/**
 * SessionList.tsx — sidebar component listing prior sessions.
 *
 * On mount, calls fetchSessions() (GET /sessions with Bearer) and renders
 * session titles. Clicking a session calls fetchSessionTurns(id)
 * (GET /sessions/{id}) and invokes the onSelectSession callback with the
 * session_id and its turn history — so ChatWindow can restore full history.
 *
 * Refreshing the page re-fetches the session list, giving cross-reload
 * session persistence at the UI level (POLISH-01 slice 11).
 *
 * Security: Bearer token sent on each request; ownership is enforced
 * server-side (T-02-03-02). No raw HTML is rendered here.
 */

import { useEffect, useState } from "react";
import { fetchSessions, fetchSessionTurns } from "@/lib/api";
import type { Message, SessionSummary, SessionTurn } from "@/lib/types";

/** Convert backend SessionTurn[] into local Message[] for ChatWindow. */
function turnsToMessages(turns: SessionTurn[]): Message[] {
  return turns.map((t) => ({
    role: t.role,
    content: t.content,
    citations: [],
  }));
}

interface SessionListProps {
  /**
   * Called when the user clicks a session entry.
   * @param sessionId  The selected session UUID.
   * @param messages   The restored turn history as local Message objects.
   */
  onSelectSession: (sessionId: string, messages: Message[]) => void;
  /** The currently active session_id (for visual highlight). */
  activeSessionId?: string;
}

export default function SessionList({
  onSelectSession,
  activeSessionId,
}: SessionListProps) {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingSessionId, setLoadingSessionId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Fetch sessions on mount (and whenever the component remounts — cross-reload persistence)
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetchSessions()
      .then((list) => {
        if (!cancelled) {
          setSessions(list);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          const msg =
            err instanceof Error ? err.message : "Failed to load sessions";
          // 401 is expected when not logged in — show a quiet prompt rather than an error
          if (msg.includes("401")) {
            setSessions([]);
          } else {
            setError(msg);
          }
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  async function handleSelect(sessionId: string) {
    if (loadingSessionId) return;
    setLoadingSessionId(sessionId);
    try {
      const turns = await fetchSessionTurns(sessionId);
      onSelectSession(sessionId, turnsToMessages(turns));
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : "Failed to load session history";
      setError(msg);
    } finally {
      setLoadingSessionId(null);
    }
  }

  return (
    <aside className="w-64 flex-shrink-0 bg-gray-900 border-r border-gray-800 flex flex-col h-full overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-800">
        <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">
          Sessions
        </p>
      </div>

      <div className="flex-1 overflow-y-auto">
        {loading && (
          <p className="text-xs text-gray-500 px-4 py-3 animate-pulse">
            Loading sessions…
          </p>
        )}

        {!loading && error && (
          <p className="text-xs text-red-400 px-4 py-3 break-words">{error}</p>
        )}

        {!loading && !error && sessions.length === 0 && (
          <p className="text-xs text-gray-600 px-4 py-3">No sessions yet.</p>
        )}

        {!loading &&
          sessions.map((s) => {
            const isActive = s.session_id === activeSessionId;
            const isLoadingThis = s.session_id === loadingSessionId;

            return (
              <button
                key={s.session_id}
                onClick={() => handleSelect(s.session_id)}
                disabled={!!loadingSessionId}
                className={`w-full text-left px-4 py-2.5 text-sm border-b border-gray-800 transition-colors
                  ${isActive
                    ? "bg-gray-700 text-white"
                    : "text-gray-300 hover:bg-gray-800 hover:text-white"
                  }
                  disabled:cursor-wait`}
                title={s.title}
              >
                <span className="block truncate">
                  {isLoadingThis ? (
                    <span className="text-gray-500 animate-pulse">Loading…</span>
                  ) : (
                    s.title || "(untitled)"
                  )}
                </span>
              </button>
            );
          })}
      </div>
    </aside>
  );
}
