"""A minimal LangGraph tool-calling loop and stream adapter for TaskPilot."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    message_chunk_to_message,
)
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, MessagesState, StateGraph

from app.exceptions import AIInvalidOutputError
from app.schemas import PendingActionView, TaskCandidate

logger = logging.getLogger("taskpilot.agent.graph")

ACTION_KINDS = {
    "create_draft",
    "create_tasks_draft",
    "complete_draft",
    "update_draft",
    "delete_draft",
    "batch_reschedule_draft",
    "breakdown_draft",
    "daily_plan_draft",
    "report_draft",
    "replan_draft",
    "project_draft",
}


@dataclass(frozen=True)
class AgentRunResult:
    message: str
    action: PendingActionView | None = None
    candidates: list[TaskCandidate] = field(default_factory=list)


@dataclass(frozen=True)
class AgentStatusEvent:
    phase: str


@dataclass(frozen=True)
class AgentTokenEvent:
    delta: str


@dataclass(frozen=True)
class AgentCompletedEvent:
    result: AgentRunResult


AgentStreamEvent = AgentStatusEvent | AgentTokenEvent | AgentCompletedEvent


def _text_content(message: BaseMessage) -> str:
    content = message.content
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
    return str(content).strip() if content is not None else ""


def _merge_stream_chunks(chunks: list[Any]) -> BaseMessage:
    if not chunks:
        raise AIInvalidOutputError()
    if len(chunks) == 1:
        candidate = chunks[0]
        if isinstance(candidate, BaseMessage):
            return candidate
        raise AIInvalidOutputError()
    merged = chunks[0]
    for chunk in chunks[1:]:
        try:
            merged = merged + chunk
        except TypeError:
            merged = chunk
    if isinstance(merged, AIMessageChunk):
        return message_chunk_to_message(merged)
    if isinstance(merged, BaseMessage):
        return merged
    raise AIInvalidOutputError()


class AgentRunner:
    """Compile and execute the single-agent graph for one conversation turn.

    The model is injected to make the workflow fully testable without network
    access. It must implement ``bind_tools`` and return AIMessage-compatible
    runnables. The streaming path requires the runnable to support async stream.
    """

    def __init__(
        self,
        model: Any,
        tools: list[BaseTool],
        *,
        recursion_limit: int = 10,
    ) -> None:
        self.model = model
        self.tools = tools
        self.recursion_limit = recursion_limit

    def _build_graph(self) -> Any:
        tools_by_name = {tool.name: tool for tool in self.tools}
        bound_model = self.model.bind_tools(self.tools)

        def call_model(state: MessagesState) -> dict[str, list[BaseMessage]]:
            response = bound_model.invoke(state["messages"])
            if not isinstance(response, BaseMessage):
                raise AIInvalidOutputError()
            return {"messages": [response]}

        def call_tools(state: MessagesState) -> dict[str, list[BaseMessage]]:
            return _execute_tool_calls(state, tools_by_name)

        def route(state: MessagesState) -> str:
            last = state["messages"][-1]
            if isinstance(last, AIMessage) and last.tool_calls:
                return "tools"
            return "end"

        workflow = StateGraph(MessagesState)
        workflow.add_node("agent", call_model)
        workflow.add_node("tools", call_tools)
        workflow.add_edge(START, "agent")
        workflow.add_conditional_edges(
            "agent",
            route,
            {"tools": "tools", "end": END},
        )
        workflow.add_edge("tools", "agent")
        return workflow.compile()

    def _build_async_graph(self) -> Any:
        tools_by_name = {tool.name: tool for tool in self.tools}
        bound_model = self.model.bind_tools(self.tools)

        async def call_model(state: MessagesState) -> dict[str, list[BaseMessage]]:
            chunks: list[Any] = []
            async for chunk in bound_model.astream(state["messages"]):
                chunks.append(chunk)
            response = _merge_stream_chunks(chunks)
            return {"messages": [response]}

        def call_tools(state: MessagesState) -> dict[str, list[BaseMessage]]:
            return _execute_tool_calls(state, tools_by_name)

        def route(state: MessagesState) -> str:
            last = state["messages"][-1]
            if isinstance(last, AIMessage) and last.tool_calls:
                return "tools"
            return "end"

        workflow = StateGraph(MessagesState)
        workflow.add_node("agent", call_model)
        workflow.add_node("tools", call_tools)
        workflow.add_edge(START, "agent")
        workflow.add_conditional_edges(
            "agent",
            route,
            {"tools": "tools", "end": END},
        )
        workflow.add_edge("tools", "agent")
        return workflow.compile()

    @staticmethod
    def _initial_messages(
        message: str,
        system_prompt: str,
        history: Sequence[BaseMessage] | None,
    ) -> MessagesState:
        return {
            "messages": [
                SystemMessage(content=system_prompt),
                *(history or []),
                HumanMessage(content=message),
            ]
        }

    def run(
        self,
        *,
        message: str,
        system_prompt: str,
        history: Sequence[BaseMessage] | None = None,
    ) -> AgentRunResult:
        graph = self._build_graph()
        state = graph.invoke(
            self._initial_messages(message, system_prompt, history),
            config={"recursion_limit": self.recursion_limit},
        )
        messages: list[BaseMessage] = state["messages"]
        return self._parse_result(messages)

    async def astream(
        self,
        *,
        message: str,
        system_prompt: str,
        history: Sequence[BaseMessage] | None = None,
    ) -> AsyncIterator[AgentStreamEvent]:
        """Run the graph and yield statuses, safe answer tokens, and final result.

        Tokens are emitted only while the turn has not produced a write draft.
        Once a ``prepare_*`` tool runs, model prose is suppressed and the service
        returns the server's deterministic confirmation message instead.
        """

        graph = self._build_async_graph()
        messages = self._initial_messages(message, system_prompt, history)["messages"]
        suppress_tokens = False
        composing_sent = False
        final_messages: list[BaseMessage] | None = None

        yield AgentStatusEvent("thinking")
        async for event in graph.astream_events(
            {"messages": messages},
            config={"recursion_limit": self.recursion_limit},
            version="v2",
        ):
            event_name = event.get("event")
            event_data = event.get("data") or {}
            if event_name == "on_tool_start":
                tool_name = str(event.get("name") or "")
                if tool_name.startswith("prepare_"):
                    suppress_tokens = True
                    yield AgentStatusEvent("preparing_action")
                else:
                    yield AgentStatusEvent("using_tools")
            elif event_name == "on_chat_model_stream":
                chunk = event_data.get("chunk")
                if suppress_tokens or not isinstance(chunk, BaseMessage):
                    continue
                delta = _text_content(chunk)
                if delta:
                    if not composing_sent:
                        composing_sent = True
                        yield AgentStatusEvent("composing")
                    yield AgentTokenEvent(delta)
            elif event_name == "on_chain_end" and event.get("name") == "LangGraph":
                output = event_data.get("output")
                if isinstance(output, dict) and isinstance(output.get("messages"), list):
                    final_messages = output["messages"]

        if final_messages is None:
            logger.warning("Agent stream ended without a final graph state")
            raise AIInvalidOutputError()
        yield AgentCompletedEvent(self._parse_result(final_messages))

    @staticmethod
    def _tool_payloads(messages: list[BaseMessage]) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        for message in messages:
            if not isinstance(message, ToolMessage):
                continue
            raw = message.content
            if not isinstance(raw, str):
                continue
            try:
                payload = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(payload, dict):
                payloads.append(payload)
        return payloads

    def _parse_result(self, messages: list[BaseMessage]) -> AgentRunResult:
        final_text = ""
        for message in reversed(messages):
            if isinstance(message, AIMessage) and not message.tool_calls:
                final_text = _text_content(message)
                if final_text:
                    break

        payloads = self._tool_payloads(messages)

        action: PendingActionView | None = None
        for payload in reversed(payloads):
            if payload.get("kind") in ACTION_KINDS:
                action_data = payload.get("action")
                if isinstance(action_data, dict):
                    try:
                        action = PendingActionView.model_validate(action_data)
                    except Exception as exc:
                        logger.warning("Invalid action payload from tool: %s", type(exc).__name__)
                        raise AIInvalidOutputError() from exc
                break

        if action is not None:
            return AgentRunResult(
                message=f"{action.summary}。请在下方确认后执行。",
                action=action,
            )

        candidates: list[TaskCandidate] = []
        for payload in reversed(payloads):
            if payload.get("kind") == "ambiguous":
                raw_candidates = payload.get("candidates")
                if isinstance(raw_candidates, list):
                    try:
                        candidates = [
                            TaskCandidate.model_validate(candidate)
                            for candidate in raw_candidates
                            if isinstance(candidate, dict)
                        ]
                    except Exception as exc:
                        logger.warning(
                            "Invalid candidate payload from tool: %s", type(exc).__name__
                        )
                        raise AIInvalidOutputError() from exc
                break

        if candidates:
            return AgentRunResult(
                message=f"找到 {len(candidates)} 个匹配任务，请明确选择要完成的任务。",
                candidates=candidates,
            )

        for payload in reversed(payloads):
            kind = payload.get("kind")
            if kind in {
                "not_found",
                "no_pending",
                "needs_disambiguation",
                "validation_error",
                "conflict",
                "error",
            }:
                tool_message = payload.get("message")
                if isinstance(tool_message, str) and tool_message.strip():
                    return AgentRunResult(message=tool_message.strip())
                break

        if final_text:
            # Defensive guard: prose must not invent a confirmation card when
            # no write tool actually produced one.
            if "请在下方确认后执行" in final_text or "已生成待确认操作" in final_text:
                return AgentRunResult(
                    message=(
                        "我没有生成可执行的待确认操作。请再具体说明要修改、删除或完成的任务；"
                        "没有确认卡片时我不会执行任何写入。"
                    )
                )
            return AgentRunResult(message=final_text)

        for payload in reversed(payloads):
            if payload.get("kind") == "tasks":
                tasks = payload.get("tasks")
                if isinstance(tasks, list) and not tasks:
                    return AgentRunResult(message="当前没有符合条件的任务。")
                if isinstance(tasks, list):
                    titles = [
                        str(task.get("title", ""))
                        for task in tasks
                        if isinstance(task, dict) and task.get("title")
                    ]
                    if titles:
                        return AgentRunResult(
                            message=f"找到 {len(titles)} 个任务："
                            + "、".join(f"「{title}」" for title in titles)
                        )
            if payload.get("kind") == "agenda":
                counts = payload.get("counts")
                if isinstance(counts, dict):
                    return AgentRunResult(
                        message=(
                            f"当前有 {counts.get('pending', 0)} 个待完成，"
                            f"{counts.get('overdue', 0)} 个逾期，"
                            f"{counts.get('due_today', 0)} 个今天到期。"
                        )
                    )
            if payload.get("kind") == "projects":
                projects = payload.get("projects")
                if isinstance(projects, list):
                    names = [
                        str(project.get("name"))
                        for project in projects
                        if isinstance(project, dict) and project.get("name")
                    ]
                    if names:
                        return AgentRunResult(
                            message=f"找到 {len(names)} 个项目：" + "、".join(names)
                        )
            if payload.get("kind") == "planning_context":
                blocks = payload.get("blocks")
                count = len(blocks) if isinstance(blocks, list) else 0
                return AgentRunResult(
                    message=(f"已根据可用时间整理出 {count} 个候选时间块，确认前不会写入今日计划。")
                )
            if payload.get("kind") == "report_facts":
                counts = payload.get("counts")
                if isinstance(counts, dict):
                    return AgentRunResult(
                        message=(
                            f"统计期内完成 {counts.get('completed', 0)} 项，"
                            f"新建 {counts.get('created', 0)} 项，"
                            f"当前逾期 {counts.get('overdue', 0)} 项。"
                        )
                    )

        raise AIInvalidOutputError()


def _execute_tool_calls(
    state: MessagesState,
    tools_by_name: dict[str, BaseTool],
) -> dict[str, list[BaseMessage]]:
    last = state["messages"][-1]
    tool_calls = getattr(last, "tool_calls", None) or []
    outputs: list[BaseMessage] = []
    for call in tool_calls:
        call_id = str(call.get("id") or "call")
        name = str(call.get("name") or "")
        args = call.get("args", {})
        tool = tools_by_name.get(name)
        if tool is None:
            content = json.dumps(
                {"ok": False, "kind": "error", "message": "未知工具。"},
                ensure_ascii=False,
            )
        elif not isinstance(args, dict):
            content = json.dumps(
                {"ok": False, "kind": "error", "message": "工具参数格式错误。"},
                ensure_ascii=False,
            )
        else:
            try:
                content = str(tool.invoke(args))
            except Exception as exc:
                logger.warning("Tool %s failed: %s", name, type(exc).__name__)
                content = json.dumps(
                    {"ok": False, "kind": "error", "message": "工具执行失败，请稍后重试。"},
                    ensure_ascii=False,
                )
        outputs.append(ToolMessage(content=content, tool_call_id=call_id, name=name))
    return {"messages": outputs}
