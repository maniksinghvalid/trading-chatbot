"use client";

/**
 * AuthButton.tsx — auth-aware header control.
 *
 * Logged out (no access_token in localStorage): shows a "Log in" link → /login.
 * Logged in: shows the user's email (decoded from the JWT `sub`) + a "Log out"
 * button that clears the token and returns to /login.
 *
 * The email is read from the JWT payload purely for display (no verification —
 * the backend verifies on every request). No new dependencies.
 */

import { useEffect, useState } from "react";

function readEmailFromToken(): string | null {
  if (typeof window === "undefined") return null;
  const token = localStorage.getItem("access_token");
  if (!token) return null;
  try {
    const payload = JSON.parse(atob(token.split(".")[1]));
    return typeof payload.sub === "string" ? payload.sub : null;
  } catch {
    return null;
  }
}

export default function AuthButton() {
  const [email, setEmail] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setEmail(readEmailFromToken());
    setReady(true);
  }, []);

  // Avoid SSR/client flash: render nothing until we've read localStorage.
  if (!ready) return null;

  if (email) {
    return (
      <div className="ml-auto flex items-center gap-2.5">
        <span className="hidden text-xs text-paper-dim sm:block">{email}</span>
        <span
          className="grid h-8 w-8 place-items-center rounded-full bg-gradient-to-br from-amber-glow to-amber-deep font-display text-base text-ink-950"
          aria-hidden="true"
        >
          {email[0]?.toUpperCase()}
        </span>
        <button
          onClick={() => {
            localStorage.removeItem("access_token");
            window.location.href = "/login";
          }}
          className="rounded-lg border border-ink-600 px-3 py-1.5 text-xs font-medium text-paper-dim transition hover:border-loss/50 hover:text-loss"
        >
          Log out
        </button>
      </div>
    );
  }

  return (
    <a
      href="/login"
      className="ml-auto rounded-lg bg-amber-glow px-4 py-1.5 text-sm font-medium text-ink-950 transition hover:brightness-110"
    >
      Log in
    </a>
  );
}
