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
import BrandMark from "@/components/BrandMark";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

/**
 * Decorative candlestick skyline for the hero — a deterministic wave, not market
 * data (no labels, no axes). Rounded so server and browser Math.sin agree
 * (last-digit float drift otherwise trips a hydration mismatch).
 */
const r = (v: number) => Math.round(v);
const CANDLES = Array.from({ length: 34 }, (_, i) => {
  const base = 40 + Math.sin(i / 3.2) * 14 + i * 2.1;
  const open = r(base + Math.sin(i * 1.7) * 6);
  const close = r(base + Math.cos(i * 1.3) * 7);
  return {
    open,
    close,
    high: Math.max(open, close) + 3 + (i % 3) * 2,
    low: Math.min(open, close) - 3 - (i % 4) * 2,
  };
});

function Skyline() {
  return (
    <svg viewBox="0 0 340 170" className="w-full" aria-hidden="true" preserveAspectRatio="none">
      <defs>
        <linearGradient id="sky-fade" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#ffb547" stopOpacity="0.15" />
          <stop offset="1" stopColor="#ffb547" stopOpacity="1" />
        </linearGradient>
      </defs>
      {CANDLES.map((c, i) => {
        const x = 6 + i * 10;
        const up = c.close >= c.open;
        const y = (v: number) => 170 - v;
        return (
          <g key={i} opacity={0.25 + (i / CANDLES.length) * 0.75}>
            <line x1={x} x2={x} y1={y(c.high)} y2={y(c.low)} stroke={up ? "#ffb547" : "#6d6a63"} strokeWidth="1" />
            <rect
              x={x - 3}
              width="6"
              y={y(Math.max(c.open, c.close))}
              height={Math.max(2, Math.abs(c.close - c.open))}
              rx="1"
              fill={up ? "url(#sky-fade)" : "#2a3142"}
              stroke={up ? "none" : "#6d6a63"}
              strokeWidth="0.75"
            />
          </g>
        );
      })}
    </svg>
  );
}

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
    <main className="desk-backdrop grid min-h-dvh lg:grid-cols-[1.15fr_1fr]">
      {/* Hero */}
      <section className="relative hidden flex-col justify-between overflow-hidden border-r border-ink-700/70 p-12 lg:flex">
        <div className="flex items-center gap-3">
          <BrandMark className="h-10 w-10" />
          <span className="font-display text-2xl">
            Night <span className="italic text-amber-glow">Desk</span>
          </span>
        </div>

        <div className="animate-rise">
          <p className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.25em] text-amber-glow">
            <span className="h-px w-8 bg-amber-glow/60" />
            trading research, grounded
          </p>
          <h1 className="mt-5 max-w-xl font-display text-7xl leading-[0.98] text-paper">
            Your reports,
            <br />
            <span className="italic text-amber-glow">in conversation.</span>
          </h1>
          <p className="mt-6 max-w-md text-[15px] leading-relaxed text-paper-dim">
            Ask questions across every analysis, options and technical report you have
            filed. Each answer cites the memo it came from.
          </p>
        </div>

        <div className="-mx-12 -mb-12 opacity-90">
          <Skyline />
        </div>
      </section>

      {/* Form */}
      <section className="flex items-center justify-center px-5 py-12">
        <div className="animate-rise w-full max-w-sm">
          <div className="mb-10 flex items-center gap-3 lg:hidden">
            <BrandMark />
            <span className="font-display text-2xl">
              Night <span className="italic text-amber-glow">Desk</span>
            </span>
          </div>

          <p className="font-mono text-[10px] uppercase tracking-[0.25em] text-paper-mute">
            Sign in
          </p>
          <h2 className="mt-2 font-display text-4xl text-paper">Open the desk.</h2>
          <p className="mb-8 mt-2 text-sm text-paper-dim">
            We&apos;ll email you a one-time login link — no password needed.
          </p>

          {status === "sent" ? (
            <div className="rounded-2xl border border-gain/30 bg-gain/10 p-5 text-sm leading-relaxed text-paper">
              <p className="mb-1 font-mono text-[10px] uppercase tracking-[0.2em] text-gain">
                ● Link sent
              </p>
              Check your inbox — we sent a login link to{" "}
              <span className="font-medium text-gain">{email}</span>. It expires in 15 minutes.
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="flex flex-col gap-4">
              <label className="flex flex-col gap-2">
                <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-paper-mute">
                  Email address
                </span>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  required
                  disabled={status === "loading"}
                  className="rounded-xl border border-ink-600 bg-ink-900/80 px-4 py-3 text-paper placeholder:text-paper-mute transition focus:border-amber-glow/60 focus:outline-none focus:ring-4 focus:ring-amber-glow/10 disabled:opacity-50"
                />
              </label>

              {status === "error" && <p className="text-sm text-loss">{errorMsg}</p>}

              <button
                type="submit"
                disabled={status === "loading" || !email.trim()}
                className="group flex items-center justify-center gap-2 rounded-xl bg-amber-glow px-4 py-3 font-medium text-ink-950 transition hover:brightness-110 focus:outline-none focus:ring-4 focus:ring-amber-glow/25 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {status === "loading" ? "Sending…" : "Send login link"}
                <span className="transition group-hover:translate-x-0.5" aria-hidden="true">
                  →
                </span>
              </button>
            </form>
          )}

          <p className="mt-10 text-[11px] leading-relaxed text-paper-mute">
            Educational research only. Nothing here is financial advice.
          </p>
        </div>
      </section>
    </main>
  );
}
