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

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


settings = Settings()
