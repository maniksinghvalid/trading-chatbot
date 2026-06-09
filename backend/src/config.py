"""
config.py — Pydantic Settings for the trading-chatbot backend.

All fields are read from environment variables (or a .env file via pydantic-settings).
The module-level `settings` instance is the single source of truth for runtime config.
"""

from pydantic_settings import BaseSettings


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

    # CORS
    cors_origins: list[str] = ["http://localhost:3000"]

    # Auth — magic-link + JWT (slice 8 / AUTH-01)
    # jwt_secret: used for HS256 signing of both magic-link tokens and session JWTs.
    # Set JWT_SECRET in the environment (already pre-set by the orchestrator).
    jwt_secret: str = ""
    jwt_ttl_hours: int = 24
    email_provider_api_key: str = ""  # Resend API key (set EMAIL_PROVIDER_API_KEY)
    magic_link_base_url: str = "http://localhost:8000/auth/callback"
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
