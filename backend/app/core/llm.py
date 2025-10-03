from __future__ import annotations
import json
import logging
from collections.abc import AsyncIterator, Iterable
from typing import Any, Dict, Optional

try:  # pragma: no cover - optional dependency for tests
    import aiohttp
except ImportError:  # pragma: no cover
    aiohttp = None  # type: ignore[assignment]

from ..config import settings

LOGGER = logging.getLogger(__name__)


class LLMNotConfiguredError(RuntimeError):
    """Raised when Ark credentials are not available."""


async def chat_stream(
    messages: Iterable[Dict[str, Any]],
    *,
    model: str | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    extra_headers: Optional[Dict[str, str]] = None,
) -> AsyncIterator[str]:
    """Stream chat completion chunks from the Ark OpenAI-compatible endpoint.

    Parameters
    ----------
    messages:
        The conversation messages to send to the Ark endpoint.
    model:
        Optional override for the model identifier.
    temperature:
        Optional sampling temperature.
    top_p:
        Optional nucleus sampling probability.
    extra_headers:
        Extra HTTP headers to merge into the request.

    Yields
    ------
    str
        Raw content deltas as they are streamed from the upstream service.
    """

    if aiohttp is None:
        raise RuntimeError("aiohttp is required for chat_stream")
    if not settings.llm_credentials_ready:
        raise LLMNotConfiguredError("Ark credentials are not configured")

    payload: Dict[str, Any] = {
        "model": model or settings.ark_model_id,
        "messages": list(messages),
        "stream": True,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if top_p is not None:
        payload["top_p"] = top_p

    headers = {
        "Authorization": f"Bearer {settings.ark_api_key}",
        "Content-Type": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)

    url = f"{settings.ark_base_url.rstrip('/')}/v1/chat/completions"
    timeout = aiohttp.ClientTimeout(total=60)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, headers=headers, json=payload) as response:
            response.raise_for_status()
            async for line in response.content:
                if not line:
                    continue
                for chunk in line.decode("utf-8").splitlines():
                    if not chunk or not chunk.startswith("data:"):
                        continue
                    data = chunk.removeprefix("data:").strip()
                    if data == "[DONE]":
                        return
                    try:
                        parsed = json.loads(data)
                    except json.JSONDecodeError:
                        LOGGER.debug("Skipping non-JSON stream fragment: %s", data)
                        continue
                    choices = parsed.get("choices") or []
                    for choice in choices:
                        delta = choice.get("delta", {})
                        content = delta.get("content")
                        if content:
                            yield content


__all__ = ["chat_stream", "LLMNotConfiguredError"]