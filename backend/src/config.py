"""
config.py — Pydantic Settings for the trading-chatbot backend.

All fields are read from environment variables (or a .env file via pydantic-settings).
The module-level `settings` instance is the single source of truth for runtime config.
"""

from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode


class Settings(BaseSettings):
    # Pinecone (read-only consumer key)
    pinecone_read_key: str = ""
    pinecone_index: str = "trade-reports"
    pinecone_namespace: str = "trade"

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    # Database (SQLite for Phase 1; switchable to Postgres in Phase 2)
    database_url: str = "sqlite:///./chat.db"

    @field_validator("database_url", mode="before")
    @classmethod
    def _force_psycopg_driver(cls, v):
        # This project ships psycopg v3 only (no psycopg2). SQLAlchemy maps the
        # bare "postgresql://" / "postgres://" schemes to the psycopg2 dialect,
        # which then fails with ModuleNotFoundError. The Supabase dashboard (and
        # most tools) hand out exactly those bare schemes, so normalize them to
        # the psycopg3 driver here rather than relying on every pasted URL to
        # include "+psycopg" by hand.
        if isinstance(v, str):
            for prefix in ("postgresql://", "postgres://"):
                if v.startswith(prefix):
                    return "postgresql+psycopg://" + v[len(prefix):]
        return v

    # CORS — accepts a comma-separated string from the environment
    # (e.g. CORS_ORIGINS=http://localhost:3000,https://app.example.com).
    # NoDecode disables pydantic-settings' default JSON decoding so the raw
    # string reaches the validator below instead of failing JSON parsing.
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, v):
        # Accept BOTH supported env formats:
        #   - JSON array:  CORS_ORIGINS=["http://a","http://b"]
        #   - CSV string:  CORS_ORIGINS=http://a,http://b
        # NoDecode disabled pydantic's automatic JSON parsing, so a JSON-array
        # string would otherwise be kept literally (brackets and quotes intact)
        # and never match a real Origin header — handle it explicitly here.
        if isinstance(v, str):
            s = v.strip()
            if s.startswith("["):
                import json

                try:
                    parsed = json.loads(s)
                    if isinstance(parsed, list):
                        return [str(o).strip() for o in parsed if str(o).strip()]
                except json.JSONDecodeError:
                    pass  # fall through to CSV parsing
            return [origin.strip() for origin in s.split(",") if origin.strip()]
        return v

    # Auth — magic-link + JWT (slice 8 / AUTH-01)
    # jwt_secret: used for HS256 signing of both magic-link tokens and session JWTs.
    # Set JWT_SECRET in the environment (already pre-set by the orchestrator).
    jwt_secret: str = ""
    jwt_ttl_hours: int = 24
    email_provider_api_key: str = ""  # Resend API key (set EMAIL_PROVIDER_API_KEY)
    # The magic-link URL must point at the FRONTEND callback page (which exchanges
    # the token for a JWT, stores it, and redirects to chat) — NOT the backend
    # endpoint, which would just render raw JSON in the browser.
    magic_link_base_url: str = "http://localhost:3000/auth/callback"
    frontend_base_url: str = "http://localhost:3000"
    # Magic-link email sender. MUST be a Resend-verified domain in production.
    # Default is Resend's shared test sender, which delivers ONLY to the Resend
    # account owner's own email — fine for local/dev. Set MAGIC_LINK_FROM_EMAIL
    # to "Name <noreply@your-verified-domain>" once your domain shows Verified.
    magic_link_from_email: str = "Trading Chatbot <onboarding@resend.dev>"

    # Rate limiting + cost (slice 10 / RATE-01)
    # ~50 turns/day single-user ceiling from cost table; 200 gives ample headroom
    # for multiple users on a shared instance without runaway spend risk.
    daily_request_budget: int = 200
    # ~50 turns × ~2k input tokens/turn × 10 users = 1M/day; set 2M for headroom
    daily_input_token_budget: int = 2_000_000
    # Admin token for GET /admin/budgets — set ADMIN_TOKEN in the environment
    admin_token: str = "change-me-in-production"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


settings = Settings()
