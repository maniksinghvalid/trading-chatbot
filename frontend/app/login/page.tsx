"use client";

/**
 * login/page.tsx — Magic-link login page.
 *
 * Renders an email input form that POSTs to the backend's
 * POST /auth/request-link endpoint.  On success, shows a confirmation
 * message asking the user to check their email.
 *
 * The magic-link callback is handled by app/auth/callback/page.tsx,
 * which reads the ?token= query param, exchanges it for a JWT, and
 * stores the JWT in localStorage as "access_token".
 *
 * Security:
 *   - The raw magic-link token is never stored in localStorage (only the JWT).
 *   - The JWT is stored under the key "access_token" and sent as
 *     Authorization: Bearer <token> on subsequent API calls.
 *   - No error details from the backend are surfaced to the user.
 */

import { useState, FormEvent } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<"idle" | "loading" | "sent" | "error">(
    "idle"
  );
  const [errorMsg, setErrorMsg] = useState("");

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();

    if (!email.trim()) return;

    setStatus("loading");
    setErrorMsg("");

    try {
      const resp = await fetch(`${API_BASE}/auth/request-link`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim() }),
      });

      if (resp.ok) {
        setStatus("sent");
      } else {
        setStatus("error");
        setErrorMsg("Unable to send login link. Please try again.");
      }
    } catch {
      setStatus("error");
      setErrorMsg("Network error. Please check your connection and try again.");
    }
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-gray-950 px-4">
      <div className="w-full max-w-sm rounded-2xl border border-gray-800 bg-gray-900 p-8 shadow-xl">
        <h1 className="mb-2 text-2xl font-bold text-white">Trading Chatbot</h1>
        <p className="mb-6 text-sm text-gray-400">
          Enter your email to receive a login link.
        </p>

        {status === "sent" ? (
          <div className="rounded-lg bg-green-900/30 border border-green-700 px-4 py-3 text-green-300 text-sm">
            Check your inbox — we sent a login link to{" "}
            <span className="font-medium">{email}</span>. It expires in 15
            minutes.
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <label className="flex flex-col gap-1">
              <span className="text-sm text-gray-300">Email address</span>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                required
                disabled={status === "loading"}
                className="rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
              />
            </label>

            {status === "error" && (
              <p className="text-sm text-red-400">{errorMsg}</p>
            )}

            <button
              type="submit"
              disabled={status === "loading" || !email.trim()}
              className="rounded-lg bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-gray-900 disabled:cursor-not-allowed disabled:opacity-50 transition-colors"
            >
              {status === "loading" ? "Sending…" : "Send login link"}
            </button>
          </form>
        )}
      </div>
    </main>
  );
}
