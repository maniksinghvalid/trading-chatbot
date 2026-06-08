"""
llm_client.py — Thin, provider-agnostic OpenAI wrapper.

Exposes a single public function:
  complete(system, messages) -> str

The wrapper prepends the system prompt as a {"role":"system"} message, calls
OpenAI Chat Completions, and returns the text of the first choice.

Error handling:
  - On any OpenAI API error (AuthenticationError, RateLimitError, APIError, etc.)
    raises LLMProviderError.  The chat route catches this and returns HTTP 503
    with a generic "LLM provider unavailable" body — never leaking the key or
    the raw error details to the client (T-03-03).

A `stream_complete` async generator will be added in slice 4 (SSE streaming).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class LLMProviderError(RuntimeError):
    """Raised when the OpenAI API returns an error or is unreachable.

    Route handlers catch this and return HTTP 503 with a generic body so that
    no API-key material or stack trace leaks to the caller (T-03-03).
    """


def complete(system: str, messages: list[dict[str, Any]]) -> str:
    """Call the OpenAI Chat Completions API and return the text response.

    The `system` prompt is prepended as the first message with role "system".
    The `messages` list typically contains one entry with role "user" for
    non-streaming, non-multi-turn calls; subsequent slices will pass the full
    conversation history here.

    Args:
        system:   The system-role prompt (SYSTEM_PROMPT from prompts.py).
        messages: List of {"role": ..., "content": ...} message dicts.
                  Prepended with the system message internally.

    Returns:
        The assistant's text response (response.choices[0].message.content).

    Raises:
        LLMProviderError: on any OpenAI API failure, so callers can return 503
                          without leaking error details (T-03-03).
    """
    from openai import OpenAI, APIError, AuthenticationError, RateLimitError

    from src.config import settings

    client = OpenAI(api_key=settings.openai_api_key)

    # Prepend the system message
    full_messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        *messages,
    ]

    try:
        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=full_messages,  # type: ignore[arg-type]
            max_tokens=2048,
        )
    except AuthenticationError as exc:
        logger.error("llm_client.complete: authentication error (check OPENAI_API_KEY): %s", exc)
        raise LLMProviderError("LLM provider unavailable") from exc
    except RateLimitError as exc:
        logger.error("llm_client.complete: rate limit exceeded: %s", exc)
        raise LLMProviderError("LLM provider unavailable") from exc
    except APIError as exc:
        logger.error("llm_client.complete: OpenAI API error: %s", exc)
        raise LLMProviderError("LLM provider unavailable") from exc
    except Exception as exc:
        logger.error("llm_client.complete: unexpected error: %s", exc)
        raise LLMProviderError("LLM provider unavailable") from exc

    return response.choices[0].message.content or ""
