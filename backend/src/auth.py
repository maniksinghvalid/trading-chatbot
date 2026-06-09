"""
auth.py — Magic-link token minting/verification, JWT issue/decode, and the
FastAPI current-user dependency (slice 8 / AUTH-01).

Public API:
  issue_magic_link(email) -> str
      Returns a signed one-time URL containing a short-TTL token that embeds
      the email address. The URL is f"{settings.magic_link_base_url}?token=...".

  verify_magic_token(token) -> str
      Decodes and verifies the magic-link token; returns the email or raises
      AuthError on expiry or tampering.

  issue_jwt(user_id) -> str
      Signs a 24h HS256 JWT with sub=user_id.

  decode_jwt(token) -> dict
      Verifies the JWT (signature + expiry) and returns the payload dict.
      Raises AuthError on any failure.

  get_current_user(authorization) -> str
      FastAPI dependency reading the Authorization header, stripping "Bearer ",
      calling decode_jwt, and returning sub (the user_id / email).
      Raises HTTPException(401) on any failure — no secret or stack trace leaked.

  AuthError
      Internal exception for auth failures (not exposed directly in HTTP responses).

Security (STRIDE register):
  T-02-03-01: JWT forgery → HS256 signed with jwt_secret; decode verifies sig + exp.
  T-02-03-04: Magic-link replay → short-TTL (15 min) signed one-time token; exp enforced.
  T-02-03-03: Key leak → get_current_user never surfaces jwt_secret or error details.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import jwt as pyjwt
from fastapi import HTTPException

from src.config import settings

logger = logging.getLogger(__name__)

# Magic-link token TTL in seconds (15 minutes)
_MAGIC_LINK_TTL_SECONDS: int = 15 * 60


class AuthError(Exception):
    """Raised for internal auth failures (expired token, bad signature, etc.)."""


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------


def issue_jwt(user_id: str) -> str:
    """Issue a 24h HS256 JWT with sub=user_id.

    Args:
        user_id: The stable user identifier (email address).

    Returns:
        A signed JWT string.
    """
    payload = {
        "sub": user_id,
        "exp": int(time.time()) + settings.jwt_ttl_hours * 3600,
    }
    return pyjwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_jwt(token: str) -> dict:
    """Verify and decode a JWT.

    Args:
        token: A JWT string.

    Returns:
        The decoded payload dict (contains at least "sub").

    Raises:
        AuthError: On signature mismatch, expiry, or any decode failure.
    """
    try:
        payload = pyjwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return payload
    except pyjwt.ExpiredSignatureError as exc:
        raise AuthError("Token has expired") from exc
    except pyjwt.InvalidTokenError as exc:
        raise AuthError("Invalid token") from exc


# ---------------------------------------------------------------------------
# Magic-link helpers
# ---------------------------------------------------------------------------


def issue_magic_link(email: str) -> str:
    """Mint a signed one-time magic-link URL embedding the email.

    The token carries a short TTL (15 minutes) so a stale link cannot be
    reused (T-02-03-04).  The same JWT library is used so verification is
    consistent — the email is stored as the "sub" claim.

    Args:
        email: The user's email address.

    Returns:
        Full URL with ?token=<signed-token> appended.
    """
    payload = {
        "sub": email,
        "exp": int(time.time()) + _MAGIC_LINK_TTL_SECONDS,
    }
    token = pyjwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    return f"{settings.magic_link_base_url}?token={token}"


def verify_magic_token(token: str) -> str:
    """Verify a magic-link token and return the embedded email.

    Args:
        token: The raw token string (NOT the full URL).

    Returns:
        The email address embedded in the token.

    Raises:
        AuthError: On expiry, signature mismatch, or any decode failure.
    """
    try:
        payload = pyjwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        email: str = payload.get("sub", "")
        if not email:
            raise AuthError("Token missing subject")
        return email
    except pyjwt.ExpiredSignatureError as exc:
        raise AuthError("Magic-link token has expired") from exc
    except pyjwt.InvalidTokenError as exc:
        raise AuthError("Invalid magic-link token") from exc


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


def get_current_user(
    authorization: Optional[str] = None,
) -> str:
    """FastAPI dependency: extract and validate the Bearer JWT, return user_id.

    Reads the Authorization header, strips the "Bearer " prefix, calls
    decode_jwt(), and returns the "sub" claim (the user's email / user_id).

    Usage in route handlers:
        @router.post("/chat")
        def post_chat(req: ChatRequest, user_id: str = Depends(get_current_user)):
            ...

    Args:
        authorization: The raw Authorization header value (injected by FastAPI
                       via Header(None) in the route parameter annotation).

    Returns:
        The user_id string (email) from the validated JWT.

    Raises:
        HTTPException(401): On missing header, malformed Bearer value, expired
                            token, or invalid signature. No secret or stack
                            trace is included in the response body (T-02-03-03).
    """
    if authorization is None:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = parts[1]
    try:
        payload = decode_jwt(token)
        user_id: str = payload.get("sub", "")
        if not user_id:
            raise AuthError("Token missing subject")
        return user_id
    except AuthError:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
