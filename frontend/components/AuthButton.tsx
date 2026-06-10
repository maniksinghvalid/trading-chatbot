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
      <div className="ml-auto flex items-center gap-3">
        <span className="text-xs text-gray-400 hidden sm:block">{email}</span>
        <button
          onClick={() => {
            localStorage.removeItem("access_token");
            window.location.href = "/login";
          }}
          className="rounded-lg bg-gray-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-gray-600 transition-colors"
        >
          Log out
        </button>
      </div>
    );
  }

  return (
    <a
      href="/login"
      className="ml-auto rounded-lg bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-500 transition-colors"
    >
      Log in
    </a>
  );
}
