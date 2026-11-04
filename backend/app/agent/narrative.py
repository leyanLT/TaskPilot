"""Single-purpose model call used to word the qualitative report sections.

This is not a second agent: it has no tools, no database access, and its output
is appended to statistics that the backend already computed.
"""

from __future__ import annotations

from collections.abc import Callable

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.llm import build_chat_model
from app.config import Settings

REPORT_SYSTEM_PROMPT = (
    "你是 TaskPilot 的报告写作助手。你只能依据用户提供的 JSON 事实写作，"
    "不得编造任务、数字、日期或完成情况，不得修改统计数字。"
    "输出中文纯文本，分为「存在的问题」和「后续建议」两节，每节 2-4 条，"
    "每条以「- 」开头，不要输出其他内容。"
)


def _message_text(message: object) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts).strip()
    return str(content).strip()


def build_report_narrative_writer(settings: Settings) -> Callable[[str], str]:
    """Return a callable that turns a facts prompt into two short sections."""

    model = build_chat_model(settings)

    def write(prompt: str) -> str:
        response = model.invoke(
            [SystemMessage(content=REPORT_SYSTEM_PROMPT), HumanMessage(content=prompt)]
        )
        return _message_text(response)

    return write
