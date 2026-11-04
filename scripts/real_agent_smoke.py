"""Real-model smoke test for the V1.5 agent tools.

Run against an isolated TaskPilot backend (never the live database), for example:

    docker run -d --rm --name taskpilot-real-smoke --env-file .env \
        -e DATABASE_URL=sqlite:////tmp/smoke.db \
        -p 127.0.0.1:8010:8000 taskpilot-backend
    python scripts/real_agent_smoke.py --base-url http://127.0.0.1:8010/api

The script needs a configured DEEPSEEK_API_KEY in the backend, costs real model
calls, and prints one RESULT line per scenario. Real model output is
non-deterministic; a missing action is reported, never treated as success.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

TZ = ZoneInfo("Asia/Shanghai")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8010/api")
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    client = httpx.Client(base_url=args.base_url, timeout=args.timeout)
    now = datetime.now(TZ)
    today = now.date()
    results: list[str] = []

    def post(path: str, payload: dict) -> dict:
        response = client.post(path, json=payload)
        response.raise_for_status()
        return response.json()

    def get(path: str) -> object:
        response = client.get(path)
        response.raise_for_status()
        return response.json()

    def ask(message: str) -> dict:
        turn = post("/assistant/messages", {"message": message})
        assistant = turn["assistant_message"]
        action = assistant.get("action")
        return {
            "content": assistant.get("content", ""),
            "action": action,
            "candidates": assistant.get("candidates") or [],
        }

    def confirm(action_id: str, overrides: dict | None = None) -> dict:
        body: dict[str, object] = {"action_id": action_id, "confirm": True}
        if overrides is not None:
            body["payload_overrides"] = overrides
        return post("/assistant/confirm", body)

    def iso(day_offset: int, hour: int, minute: int = 0) -> str:
        value = datetime.combine(
            today + timedelta(days=day_offset), datetime.min.time(), tzinfo=TZ
        ).replace(hour=hour, minute=minute)
        return value.isoformat()

    def record(name: str, status: str, detail: object) -> None:
        results.append(
            f"RESULT {name} {status} {json.dumps(detail, ensure_ascii=False)}"
        )

    # --- seed a small realistic dataset -------------------------------------
    project = post(
        "/projects",
        {
            "name": "AI Agent 项目",
            "description": "两周内完成一个可用的 AI Agent 原型。",
            "status": "active",
            "start_date": today.isoformat(),
            "due_date": (today + timedelta(days=14)).isoformat(),
        },
    )
    post(
        "/tasks",
        {
            "title": "设计 Agent 架构",
            "project_id": project["id"],
            "priority": "high",
            "estimated_minutes": 120,
            "due_at": iso(1, 18),
        },
    )
    post(
        "/tasks",
        {
            "title": "实现工具调用",
            "project_id": project["id"],
            "priority": "medium",
            "estimated_minutes": 180,
            "due_at": iso(3, 18),
        },
    )
    post(
        "/tasks",
        {
            "title": "整理周报素材",
            "priority": "low",
            "estimated_minutes": 30,
            "due_at": iso(2, 12),
        },
    )
    completed = post(
        "/tasks",
        {
            "title": "确认需求范围",
            "project_id": project["id"],
            "priority": "medium",
            "estimated_minutes": 45,
            "due_at": iso(0, 12),
        },
    )
    client.patch(
        f"/tasks/{completed['id']}", json={"status": "completed"}
    ).raise_for_status()

    # --- A. task breakdown ---------------------------------------------------
    try:
        turn = ask(
            "我需要在两周内完成一个 AI Agent 项目，帮我拆解任务。"
            "项目就用「AI Agent 项目」，请直接生成可确认的任务拆解草稿，"
            "包含优先级、预计耗时、截止时间和子任务。"
        )
        action = turn["action"]
        if not action or action.get("action_type") != "create_task_breakdown":
            record(
                "breakdown",
                "NO_ACTION",
                {"content": turn["content"][:300]},
            )
        else:
            before = len(get("/tasks?include_subtasks=true"))
            first = confirm(action["id"])
            after = len(get("/tasks?include_subtasks=true"))
            replay = confirm(action["id"])
            final = len(get("/tasks?include_subtasks=true"))
            record(
                "breakdown",
                "PASS" if after > before and final == after else "FAIL",
                {
                    "created": after - before,
                    "idempotent": final == after,
                    "status": first.get("status"),
                    "replay_status": replay.get("status"),
                },
            )
    except Exception as exc:  # noqa: BLE001 - smoke script reports and continues
        record("breakdown", "ERROR", {"error": f"{type(exc).__name__}: {exc}"[:300]})

    # --- B. daily plan for tomorrow (today may already be over) ------------
    tomorrow = today + timedelta(days=1)
    try:
        turn = ask(
            "帮我安排明天的工作，我有 3 小时，生成明天的今日计划草稿。"
            "只安排真实存在的待办任务，不要超时。"
        )
        action = turn["action"]
        if not action or action.get("action_type") != "save_daily_plan":
            record("daily_plan", "NO_ACTION", {"content": turn["content"][:300]})
        else:
            first = confirm(action["id"])
            plan = get(f"/plans/{tomorrow.isoformat()}")
            replay = confirm(action["id"])
            plan_again = get(f"/plans/{tomorrow.isoformat()}")
            record(
                "daily_plan",
                "PASS"
                if len(plan["items"]) > 0
                and len(plan_again["items"]) == len(plan["items"])
                else "FAIL",
                {
                    "items": len(plan["items"]),
                    "planned_minutes": plan["planned_minutes"],
                    "available_minutes": plan["available_minutes"],
                    "status": first.get("status"),
                    "replay_status": replay.get("status"),
                },
            )
    except Exception as exc:  # noqa: BLE001
        record("daily_plan", "ERROR", {"error": f"{type(exc).__name__}: {exc}"[:300]})

    # --- C. priority suggestions (read-only) --------------------------------
    try:
        turn = ask("帮我看一下待办任务的优先级建议，并逐条说明理由。不要修改任何任务。")
        content = turn["content"]
        record(
            "priority",
            "PASS"
            if turn["action"] is None and ("建议" in content or "优先级" in content)
            else "UNEXPECTED_ACTION",
            {"content": content[:500]},
        )
    except Exception as exc:  # noqa: BLE001
        record("priority", "ERROR", {"error": f"{type(exc).__name__}: {exc}"[:300]})

    # --- D. report draft -----------------------------------------------------
    try:
        turn = ask("帮我生成今天的工作日报，并保存成报告草稿。")
        action = turn["action"]
        if not action or action.get("action_type") != "save_report":
            record("report", "NO_ACTION", {"content": turn["content"][:300]})
        else:
            before = len(get("/reports"))
            first = confirm(action["id"])
            after = len(get("/reports"))
            replay = confirm(action["id"])
            final = len(get("/reports"))
            report_id = replay.get("report_id") or first.get("report_id")
            content = get(f"/reports/{report_id}")["content_md"] if report_id else ""
            record(
                "report",
                "PASS"
                if after == before + 1 and final == after and "统计范围" in content
                else "FAIL",
                {
                    "created": after - before,
                    "idempotent": final == after,
                    "has_period": "统计范围" in content,
                    "status": first.get("status"),
                    "replay_status": replay.get("status"),
                },
            )
    except Exception as exc:  # noqa: BLE001
        record("report", "ERROR", {"error": f"{type(exc).__name__}: {exc}"[:300]})

    for line in results:
        print(line)
    client.close()
    return (
        0
        if all(" FAIL " not in line and " ERROR " not in line for line in results)
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
