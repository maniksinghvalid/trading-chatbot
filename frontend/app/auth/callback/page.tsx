"use client";

/**
 * auth/callback/page.tsx — Magic-link callback handler.
 *
 * The backend's GET /auth/callback?token=<magic-token> is invoked by the
 * magic-link email.  However, this page handles an alternative flow where the
 * frontend itself calls the backend callback endpoint (e.g., when the backend
 * redirects to frontend_base_url with the JWT in the query string, or the
 * frontend acts as the callback URL).
 *
 * Flow:
 *   1. User clicks the magic-link email, which goes to the BACKEND
 *      GET /auth/callback?token=<magic-token>.
 *   2. The backend verifies the token, mints a 24h JWT, and either:
 *      a. Returns {access_token, token_type} as JSON (when called via API), or
 *      b. Redirects to `frontend_base_url/?access_token=<jwt>` (optional flow).
 *
 * This page handles case (b): reads `access_token` from the URL query string,
 * stores it in localStorage, and redirects to the home page.
 *
 * It also handles the case where the page is the actual callback URL
 * (magic_link_base_url = http://localhost:3000/auth/callback), in which case
 * the `token` query param is the raw magic-link token and we call the backend
 * to exchange it for a JWT.
 *
 * Security: The JWT is stored in localStorage under "access_token".
 * This is acceptable for an MVP; future hardening may move to httpOnly cookies.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import BrandMark from "@/components/BrandMark";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export default function AuthCallbackPage() {
  const router = useRouter();
  const [status, setStatus] = useState<"loading" | "success" | "error">(
    "loading"
  );
  const [errorMsg, setErrorMsg] = useState("");

  useEffect(() => {
    async function handleCallback() {
      const params = new URLSearchParams(window.location.search);

      // Case 1: Backend already minted the JWT and passed it via access_token param
      const existingJwt = params.get("access_token");
      if (existingJwt) {
        localStorage.setItem("access_token", existingJwt);
        setStatus("success");
        setTimeout(() => router.push("/"), 1500);
        return;
      }

      // Case 2: Raw magic-link token — exchange it for a JWT via the backend
      const rawToken = params.get("token");
      if (!rawToken) {
        setStatus("error");
        setErrorMsg("Invalid login link. Please request a new one.");
        return;
      }

      try {
        const resp = await fetch(
          `${API_BASE}/auth/callback?token=${encodeURIComponent(rawToken)}`,
          { method: "GET" }
        );

        if (resp.ok) {
          const data = await resp.json();
          if (data.access_token) {
            localStorage.setItem("access_token", data.access_token);
            setStatus("success");
            setTimeout(() => router.push("/"), 1500);
          } else {
            throw new Error("No access_token in response");
          }
        } else {
          setStatus("error");
          setErrorMsg(
            "This login link has expired or is invalid. Please request a new one."
          );
        }
      } catch {
        setStatus("error");
        setErrorMsg("Network error. Please try again.");
      }
    }

    handleCallback();
  }, [router]);

  return (
    <main className="desk-backdrop flex min-h-dvh flex-col items-center justify-center px-4">
      <div className="animate-rise w-full max-w-sm rounded-3xl border border-ink-700 bg-ink-900/80 p-8 text-center shadow-[0_30px_80px_-30px_rgba(0,0,0,0.9)] backdrop-blur-xl">
        <BrandMark className="mx-auto mb-6 h-12 w-12" />

        {status === "loading" && (
          <>
            <div className="mx-auto mb-4 h-7 w-7 animate-spin rounded-full border-2 border-amber-glow border-t-transparent" />
            <p className="font-display text-2xl text-paper">Verifying your link…</p>
          </>
        )}

        {status === "success" && (
          <>
            <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.25em] text-gain">● Verified</p>
            <p className="font-display text-3xl text-paper">
              Welcome to the <span className="italic text-amber-glow">desk.</span>
            </p>
            <p className="mt-2 text-sm text-paper-dim">Redirecting…</p>
          </>
        )}

        {status === "error" && (
          <>
            <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.25em] text-loss">● Login failed</p>
            <p className="text-sm text-paper-dim">{errorMsg}</p>
            <a
              href="/login"
              className="mt-6 inline-block rounded-xl bg-amber-glow px-4 py-2.5 text-sm font-medium text-ink-950 transition hover:brightness-110"
            >
              Request a new login link
            </a>
          </>
        )}
      </div>
    </main>
  );
}
