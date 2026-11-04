"""DeepSeek chat model construction using the official OpenAI-compatible API."""

from __future__ import annotations

from langchain_openai import ChatOpenAI

from app.config import Settings


def build_chat_model(settings: Settings) -> ChatOpenAI:
    """Create the DeepSeek chat model.

    DeepSeek documents an OpenAI-compatible endpoint at
    https://api.deepseek.com and supports tool calls. Thinking mode is disabled
    for the short management workflow, as documented in the tool-calls guide.
    """

    return ChatOpenAI(
        model=settings.deepseek_model,
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        timeout=settings.agent_timeout_seconds,
        max_retries=settings.agent_max_retries,
        temperature=0,
        extra_body={"thinking": {"type": "disabled"}},
    )
