"""
routes/auth.py — Magic-link authentication endpoints (slice 8 / AUTH-01).

POST /auth/request-link
    Accepts {"email": "user@example.com"}, mints a magic-link URL via
    issue_magic_link(), and sends it via Resend.  Returns a generic 200
    acknowledgement — never exposes the link or the API key in the response.
    Provider errors return HTTP 503 (no key/stack trace leaked — T-02-03-03).

GET /auth/callback?token=<magic-link-token>
    Verifies the one-time signed token via verify_magic_token().
    On success, mints a 24h JWT via issue_jwt() and returns:
      {"access_token": "<jwt>", "token_type": "bearer"}
    On failure (expired/tampered token), returns HTTP 401.

Security (STRIDE register):
  T-02-03-01: JWT forgery → handled by decode_jwt in auth.py (HS256 signed).
  T-02-03-03: Info disclosure → generic 503 on send failure; no key in response.
  T-02-03-04: Tampering / replay → verify_magic_token rejects expired/tampered tokens.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr

from src.auth import AuthError, issue_jwt, issue_magic_link, verify_magic_token
from src.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class MagicLinkRequest(BaseModel):
    email: str  # plain str so tests work without email-validator installed


class MagicLinkResponse(BaseModel):
    message: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------------------------------------------------------------------------
# Internal helper — extracted so tests can monkeypatch it
# ---------------------------------------------------------------------------


def _send_magic_link_email(email: str, link: str) -> None:
    """Send the magic-link email via Resend.

    Extracted as a standalone function so tests can monkeypatch it without
    importing the full Resend SDK.  Provider failures raise RuntimeError
    which the route converts to a generic 503.

    Args:
        email: Recipient address.
        link: The signed magic-link URL to include in the email body.

    Raises:
        RuntimeError: On any Resend API error (caller converts to 503).
    """
    import resend  # lazy import — only needed at send time

    resend.api_key = settings.email_provider_api_key

    try:
        resend.Emails.send(
            {
                "from": "Trading Chatbot <noreply@updates.maniksingh.dev>",
                "to": [email],
                "subject": "Your Trading Chatbot login link",
                "html": (
                    "<p>Click the link below to log in. "
                    "It expires in 15 minutes.</p>"
                    f"<p><a href='{link}'>Log in to Trading Chatbot</a></p>"
                    "<p>If you did not request this, ignore this email.</p>"
                ),
            }
        )
    except Exception as exc:
        logger.error("_send_magic_link_email: Resend API error (details suppressed): %s", type(exc).__name__)
        raise RuntimeError("Email provider error") from exc


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/request-link", response_model=MagicLinkResponse)
def request_magic_link(body: MagicLinkRequest) -> MagicLinkResponse:
    """Issue and email a magic-link to the given address.

    The response is a generic acknowledgement — the link itself is never
    returned in the HTTP response (T-02-03-03).

    Returns HTTP 503 when the email provider fails (no key/stack trace).
    """
    link = issue_magic_link(body.email)

    try:
        _send_magic_link_email(body.email, link)
    except RuntimeError:
        raise HTTPException(
            status_code=503,
            detail="Email service temporarily unavailable",
        )

    return MagicLinkResponse(message="Magic link sent. Check your email.")


@router.get("/callback", response_model=TokenResponse)
def auth_callback(token: str) -> TokenResponse:
    """Exchange a valid magic-link token for a 24h Bearer JWT.

    Args:
        token: The raw token from the ?token= query parameter.

    Returns:
        {"access_token": "<jwt>", "token_type": "bearer"}

    Raises:
        HTTPException(401): On expired or tampered tokens.
    """
    try:
        email = verify_magic_token(token)
    except AuthError as exc:
        logger.warning("auth_callback: invalid magic token: %s", exc)
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired login link",
        )

    jwt_token = issue_jwt(email)
    return TokenResponse(access_token=jwt_token, token_type="bearer")
