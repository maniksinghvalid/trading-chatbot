"""
llm_client.py — Thin, provider-agnostic OpenAI wrapper.

Exposes two public functions:
  complete(system, messages) -> str
      Non-streaming call; returns the full assistant text.

  stream_complete(system, messages) -> Generator[str, None, None]
      Streaming generator; yields each non-empty text token from the OpenAI
      streaming response (chunk.choices[0].delta.content).  Added in slice 4.

Error handling:
  - On any OpenAI API error (AuthenticationError, RateLimitError, APIError, etc.)
    raises LLMProviderError.  The chat route catches this and returns HTTP 503
    with a generic "LLM provider unavailable" body — never leaking the key or
    the raw error details to the client (T-03-03).

  - stream_complete raises LLMProviderError on errors encountered before the
    stream starts.  Errors encountered mid-stream are re-raised as
    LLMProviderError so the SSE route can emit a terminating error event
    without leaking key material or stack traces (T-05-02).
"""

from __future__ import annotations

import logging
from typing import Any, Generator

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


def stream_complete(
    system: str,
    messages: list[dict[str, Any]],
) -> Generator[str, None, None]:
    """Stream tokens from the OpenAI Chat Completions API.

    Yields each non-empty text delta from the streaming response.  The caller
    (the /chat/stream route) buffers the yielded tokens to reconstruct the full
    assistant text for persistence and emits them as SSE `token` events.

    Args:
        system:   The system-role prompt (SYSTEM_PROMPT from prompts.py).
        messages: List of {"role": ..., "content": ...} message dicts.
                  The system message is prepended internally.

    Yields:
        str: Each non-empty delta token from chunk.choices[0].delta.content.

    Raises:
        LLMProviderError: on any OpenAI API failure encountered before or
                          during the stream, so the SSE route can emit a
                          terminating error event without leaking key material
                          or stack traces (T-05-02).
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
        stream = client.chat.completions.create(
            model=settings.openai_model,
            messages=full_messages,  # type: ignore[arg-type]
            max_tokens=2048,
            stream=True,
        )
    except AuthenticationError as exc:
        logger.error("llm_client.stream_complete: authentication error: %s", exc)
        raise LLMProviderError("LLM provider unavailable") from exc
    except RateLimitError as exc:
        logger.error("llm_client.stream_complete: rate limit exceeded: %s", exc)
        raise LLMProviderError("LLM provider unavailable") from exc
    except APIError as exc:
        logger.error("llm_client.stream_complete: OpenAI API error: %s", exc)
        raise LLMProviderError("LLM provider unavailable") from exc
    except Exception as exc:
        logger.error("llm_client.stream_complete: unexpected error: %s", exc)
        raise LLMProviderError("LLM provider unavailable") from exc

    # Iterate over the stream, yielding non-empty token deltas
    try:
        for chunk in stream:
            if chunk.choices:
                delta_content = chunk.choices[0].delta.content
                if delta_content:
                    yield delta_content
    except AuthenticationError as exc:
        logger.error("llm_client.stream_complete: mid-stream auth error: %s", exc)
        raise LLMProviderError("LLM provider unavailable") from exc
    except RateLimitError as exc:
        logger.error("llm_client.stream_complete: mid-stream rate limit: %s", exc)
        raise LLMProviderError("LLM provider unavailable") from exc
    except APIError as exc:
        logger.error("llm_client.stream_complete: mid-stream API error: %s", exc)
        raise LLMProviderError("LLM provider unavailable") from exc
    except Exception as exc:
        logger.error("llm_client.stream_complete: unexpected mid-stream error: %s", exc)
        raise LLMProviderError("LLM provider unavailable") from exc
