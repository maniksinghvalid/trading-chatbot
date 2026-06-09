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
    <main className="flex min-h-screen flex-col items-center justify-center bg-gray-950 px-4">
      <div className="w-full max-w-sm rounded-2xl border border-gray-800 bg-gray-900 p-8 shadow-xl text-center">
        {status === "loading" && (
          <>
            <div className="mb-4 text-4xl animate-spin inline-block w-8 h-8 border-4 border-blue-500 border-t-transparent rounded-full" />
            <p className="text-gray-300">Verifying your login link…</p>
          </>
        )}

        {status === "success" && (
          <>
            <div className="mb-4 text-4xl">✓</div>
            <p className="text-green-300 font-medium">Logged in successfully!</p>
            <p className="mt-1 text-sm text-gray-400">Redirecting…</p>
          </>
        )}

        {status === "error" && (
          <>
            <p className="text-red-400 font-medium">Login failed</p>
            <p className="mt-2 text-sm text-gray-400">{errorMsg}</p>
            <a
              href="/login"
              className="mt-4 inline-block text-sm text-blue-400 hover:text-blue-300 underline"
            >
              Request a new login link
            </a>
          </>
        )}
      </div>
    </main>
  );
}
