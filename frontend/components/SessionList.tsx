"use client";

/**
 * SessionList.tsx — sidebar component listing prior sessions.
 *
 * On mount, calls fetchSessions() (GET /sessions with Bearer) and renders
 * session titles. Clicking a session calls fetchSessionTurns(id)
 * (GET /sessions/{id}) and invokes the onSelectSession callback with the
 * session_id and its turn history — so ChatWindow can restore full history.
 *
 * Re-fetch triggers:
 *   1. On mount (existing behaviour — cross-reload persistence).
 *   2. When `refreshTrigger` increments (wired from page.tsx via
 *      ChatWindow.onSessionChange so a new session appears in the sidebar
 *      without a manual reload — POLISH-01 / gap-closure 02-09).
 *   3. When the access_token becomes available after the component has already
 *      mounted: a bounded 500 ms interval polls localStorage until the token
 *      appears, then triggers a re-fetch.  The interval is cleared as soon as
 *      the token is found or on unmount so it does not run indefinitely.
 *   4. On the window `storage` event (token set in another tab).
 *   5. On the window `focus` event (user returns from a login tab).
 *
 * When fetchSessions returns 401 (no token yet), the list is left empty and
 * quiet; the token-availability re-fetch will populate it once the token lands.
 *
 * Security: Bearer token sent on each request; ownership is enforced
 * server-side (T-02-03-02). No raw HTML is rendered here.
 */

import { useEffect, useRef, useState } from "react";
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
  /** The currently active session_id (for visual highlight + optimistic entry). */
  activeSessionId?: string;
  /**
   * Incrementing counter supplied by the parent page.  When this value
   * changes, SessionList re-fetches so a newly-created session appears in the
   * sidebar without a manual reload.
   */
  refreshTrigger?: number;
}

export default function SessionList({
  onSelectSession,
  activeSessionId,
  refreshTrigger,
}: SessionListProps) {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingSessionId, setLoadingSessionId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Keep track of whether a fetch is currently in-flight so the token-poll
  // and focus/storage listeners do not stack up concurrent requests.
  const fetchingRef = useRef(false);

  // ──────────────────────────────────────────────────────────────────────────
  // Primary fetch effect: re-runs on mount, on refreshTrigger change, and
  // whenever the "tokenReady" internal flag flips (see token-poll effect).
  // ──────────────────────────────────────────────────────────────────────────
  const [tokenReady, setTokenReady] = useState(() => {
    if (typeof window === "undefined") return false;
    return Boolean(localStorage.getItem("access_token"));
  });

  useEffect(() => {
    let cancelled = false;
    fetchingRef.current = true;
    setLoading(true);
    setError(null);

    fetchSessions()
      .then((list) => {
        if (!cancelled) {
          setSessions(list);
          setLoading(false);
          fetchingRef.current = false;
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          const msg =
            err instanceof Error ? err.message : "Failed to load sessions";
          // 401 is expected when not logged in — show a quiet empty list rather
          // than an error message; the token-availability poll will re-fetch.
          if (msg.includes("401")) {
            setSessions([]);
          } else {
            setError(msg);
          }
          setLoading(false);
          fetchingRef.current = false;
        }
      });

    return () => {
      cancelled = true;
    };
    // refreshTrigger: re-fetch when parent signals a new session was created.
    // tokenReady: re-fetch the first time the token becomes available after mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshTrigger, tokenReady]);

  // ──────────────────────────────────────────────────────────────────────────
  // Token-availability polling: if the token is absent on mount, poll every
  // 500 ms until it appears or the component unmounts.  Also re-fetch on
  // `storage` (token set in another tab) and `focus` (user returns from login).
  // ──────────────────────────────────────────────────────────────────────────
  useEffect(() => {
    if (typeof window === "undefined") return;

    // Helper: check the token and flip tokenReady if it just appeared.
    function checkToken() {
      const hasToken = Boolean(localStorage.getItem("access_token"));
      if (hasToken) {
        setTokenReady(true);
      }
    }

    // Re-fetch when the storage key changes in any tab.
    function onStorage(e: StorageEvent) {
      if (e.key === "access_token" || e.key === null) {
        checkToken();
        // If already tokenReady but a new refresh is needed (e.g. token updated),
        // trigger a refetch directly by marking fetching=false so the focus handler
        // picks it up, or by re-calling fetchSessions.
        if (tokenReady && !fetchingRef.current) {
          // The primary effect won't re-run (tokenReady didn't change), so
          // manually trigger a re-fetch for this edge case.
          fetchingRef.current = true;
          fetchSessions()
            .then((list) => {
              setSessions(list);
              fetchingRef.current = false;
            })
            .catch(() => {
              fetchingRef.current = false;
            });
        }
      }
    }

    // Re-fetch on focus (user returns from a login tab on the same domain).
    function onFocus() {
      if (!fetchingRef.current) {
        fetchingRef.current = true;
        fetchSessions()
          .then((list) => {
            setSessions(list);
            fetchingRef.current = false;
          })
          .catch(() => {
            fetchingRef.current = false;
          });
      }
    }

    window.addEventListener("storage", onStorage);
    window.addEventListener("focus", onFocus);

    // Only start the poll if we don't already have a token.
    let interval: ReturnType<typeof setInterval> | null = null;
    if (!tokenReady) {
      interval = setInterval(() => {
        const hasToken = Boolean(localStorage.getItem("access_token"));
        if (hasToken) {
          setTokenReady(true);
          if (interval !== null) {
            clearInterval(interval);
            interval = null;
          }
        }
      }, 500);
    }

    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener("focus", onFocus);
      if (interval !== null) {
        clearInterval(interval);
      }
    };
    // tokenReady is intentionally in deps: once the token arrives we clear the
    // interval and can stop listening to the poll branch.
  }, [tokenReady]);

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

  // ──────────────────────────────────────────────────────────────────────────
  // Optimistic entry: if the active session is not yet in the fetched list
  // (backend may not have committed the title yet), prepend a temporary stub
  // so the user sees the new session immediately.  Once the real entry arrives
  // on the next fetch it replaces the stub (deduplicated by session_id below).
  // ──────────────────────────────────────────────────────────────────────────
  const displaySessions: SessionSummary[] =
    activeSessionId && !sessions.some((s) => s.session_id === activeSessionId)
      ? [{ session_id: activeSessionId, title: "(new session)" }, ...sessions]
      : sessions;

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

        {!loading && !error && displaySessions.length === 0 && (
          <p className="text-xs text-gray-600 px-4 py-3">No sessions yet.</p>
        )}

        {!loading &&
          displaySessions.map((s) => {
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
