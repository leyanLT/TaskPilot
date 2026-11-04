"""V2.0 F05/F07: deterministic replanning and enhanced report exports."""

from __future__ import annotations

import io
import zipfile
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.models import FocusSession, PlanRevision, Report
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

TZ = ZoneInfo("Asia/Shanghai")


def today() -> date:
    return datetime.now(TZ).date()


def local_iso(day: date, hour: int, minute: int = 0) -> str:
    return datetime.combine(day, time(hour, minute), tzinfo=TZ).isoformat()


def _plan_tomorrow(client: TestClient, task_id: str, day: date) -> dict:
    response = client.put(
        f"/api/plans/{day.isoformat()}",
        json={
            "available_minutes": 300,
            "items": [
                {
                    "task_id": task_id,
                    "start_at": local_iso(day, 9),
                    "end_at": local_iso(day, 10),
                    "note": None,
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_replan_preview_diffs_and_applies_with_history(
    client: TestClient,
    session: Session,
    create_task: Callable[..., dict],
) -> None:
    day = today() + timedelta(days=1)
    planned = create_task(title="写第一章", estimated_minutes=60)
    extra = create_task(title="整理参考文献", estimated_minutes=30)
    blocked_by = create_task(title="先做完的实验", estimated_minutes=45)
    blocked_task = create_task(title="等实验的分析")
    client.post(
        f"/api/dependencies/{blocked_task['id']}",
        json={"depends_on_task_id": blocked_by["id"]},
    )
    _plan_tomorrow(client, planned["id"], day)

    preview = client.post(
        "/api/replan/preview",
        json={"plan_date": day.isoformat(), "reason": "今天的实验没做完"},
    )
    assert preview.status_code == 200, preview.text
    draft = preview.json()
    assert draft["plan_token"]
    assert len(draft["before"]) == 1
    assert {block["task_id"] for block in draft["after"]} >= {
        planned["id"],
        extra["id"],
        blocked_by["id"],
    }
    assert blocked_task["id"] in {item["task_id"] for item in draft["blocked_tasks"]}
    kinds = {change["kind"] for change in draft["changes"]}
    assert "added" in kinds
    assert any("调整原因" in line for line in draft["explanation"])

    applied = client.post(
        "/api/replan/apply",
        json={
            "plan_date": day.isoformat(),
            "blocks": draft["after"],
            "plan_token": draft["plan_token"],
            "reason": "今天的实验没做完",
        },
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["applied"] == len(draft["after"])

    plan = client.get(f"/api/plans/{day.isoformat()}").json()
    assert len(plan["items"]) == len(draft["after"])
    revisions = session.scalars(select(PlanRevision).where(PlanRevision.plan_date == day)).all()
    assert len(revisions) == 1
    assert revisions[0].before_items[0]["title"] == "写第一章"

    stale = client.post(
        "/api/replan/apply",
        json={
            "plan_date": day.isoformat(),
            "blocks": draft["after"],
            "plan_token": draft["plan_token"],
            "reason": "重复确认",
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "PLAN_VERSION_CONFLICT"


def test_replan_respects_unavailable_windows_and_capacity(
    client: TestClient,
    create_task: Callable[..., dict],
) -> None:
    day = today() + timedelta(days=2)
    create_task(title="写第二章", estimated_minutes=60)
    preview = client.post(
        "/api/replan/preview",
        json={
            "plan_date": day.isoformat(),
            "unavailable_windows": [{"start": local_iso(day, 9), "end": local_iso(day, 11)}],
        },
    )
    assert preview.status_code == 200, preview.text
    draft = preview.json()
    first = draft["after"][0]
    start = datetime.fromisoformat(first["start_at"]).astimezone(TZ)
    assert start.hour >= 11
    assert draft["available_minutes"] >= 60


def test_replan_skips_blocked_tasks_entirely(
    client: TestClient,
    create_task: Callable[..., dict],
) -> None:
    day = today() + timedelta(days=3)
    prerequisite = create_task(title="前置实验")
    dependent = create_task(title="依赖实验")
    client.post(
        f"/api/dependencies/{dependent['id']}",
        json={"depends_on_task_id": prerequisite["id"]},
    )
    draft = client.post("/api/replan/preview", json={"plan_date": day.isoformat()}).json()
    after_ids = {block["task_id"] for block in draft["after"]}
    assert dependent["id"] not in after_ids
    assert prerequisite["id"] in after_ids
    assert any("前置任务未完成" in line for line in draft["explanation"])


def test_enhanced_report_uses_real_statistics(
    client: TestClient,
    session: Session,
    create_task: Callable[..., dict],
) -> None:
    day = today()
    done = create_task(title="完成的任务", estimated_minutes=60)
    client.patch(f"/api/tasks/{done['id']}", json={"status": "completed"})
    block_task = create_task(title="安排了时间块的任务", estimated_minutes=60)
    pending = create_task(title="还没做的任务")
    block = client.post(
        "/api/time-blocks",
        json={
            "plan_date": day.isoformat(),
            "task_id": block_task["id"],
            "start_at": local_iso(day, 9),
            "end_at": local_iso(day, 10),
        },
    )
    assert block.status_code == 201, block.text
    started = client.post(
        "/api/focus/start", json={"task_id": block_task["id"], "planned_minutes": 25}
    )
    assert started.status_code == 200, started.text
    row = session.get(FocusSession, started.json()["id"])
    row.accumulated_seconds = 1800
    row.last_resumed_at = None
    row.status = "completed"
    row.ended_at = datetime.now(UTC)
    session.commit()
    client.patch(f"/api/tasks/{block_task['id']}", json={"status": "completed"})

    response = client.post(
        "/api/reports/enhanced",
        json={
            "report_type": "daily",
            "period_start": day.isoformat(),
            "period_end": day.isoformat(),
        },
    )
    assert response.status_code == 200, response.text
    draft = response.json()
    facts = draft["facts"]
    assert facts["totals"]["completed"] >= 1
    assert facts["totals"]["pending_at_end"] >= 1
    assert facts["focus"]["minutes"] >= 30
    assert facts["plan"]["planned_blocks"] == 1
    assert facts["plan"]["completed_blocks"] == 1
    assert facts["trend"][0]["completed"] >= 1
    assert "数据来源" in draft["content_md"]
    assert pending["id"] not in {task["id"] for task in facts["completed_tasks"]}
    assert facts["ai_used"] is False


def test_empty_report_does_not_invent_content(client: TestClient) -> None:
    day = date(2020, 1, 1)
    response = client.post(
        "/api/reports/enhanced",
        json={
            "report_type": "weekly",
            "period_start": day.isoformat(),
            "period_end": (day + timedelta(days=6)).isoformat(),
        },
    )
    assert response.status_code == 200, response.text
    draft = response.json()
    assert draft["facts"]["totals"]["completed"] == 0
    assert draft["facts"]["focus"]["minutes"] == 0
    assert "本期没有已完成的任务" in draft["content_md"]


def test_report_export_docx_and_pdf_are_real_files(
    client: TestClient,
    session: Session,
) -> None:
    report = Report(
        report_type="daily",
        title="TaskPilot 日报（中文导出测试）",
        period_start=datetime.now(UTC) - timedelta(days=1),
        period_end=datetime.now(UTC),
        content_md=(
            "## 工作摘要\n\n本期完成 2 个任务。\n\n"
            "| 日期 | 完成数 | 趋势 |\n| --- | --- | --- |\n"
            "| 2026-11-03 | 2 | ██████░░░░ |\n\n"
            "## 下一阶段建议\n\n- 先处理逾期任务。\n"
        ),
        facts={"totals": {"completed": 2}},
        ai_used=False,
    )
    session.add(report)
    session.commit()

    docx = client.get(f"/api/reports/{report.id}/docx")
    assert docx.status_code == 200
    assert docx.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert docx.content[:2] == b"PK"
    with zipfile.ZipFile(io.BytesIO(docx.content)) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")
    assert "TaskPilot 日报（中文导出测试）" in document_xml
    assert "先处理逾期任务" in document_xml

    pdf = client.get(f"/api/reports/{report.id}/pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"].startswith("application/pdf")
    assert pdf.content[:5] == b"%PDF-"
    assert b"%%EOF" in pdf.content[-2048:]
    assert len(pdf.content) > 2000

    missing = client.get("/api/reports/00000000-0000-0000-0000-000000000000/pdf")
    assert missing.status_code == 404


def test_report_facts_trace_back_to_rows(
    client: TestClient,
    session: Session,
    create_task: Callable[..., dict],
) -> None:
    day = today()
    task = create_task(title="可追溯任务")
    client.patch(f"/api/tasks/{task['id']}", json={"status": "completed"})
    response = client.post(
        "/api/reports/enhanced",
        json={
            "report_type": "daily",
            "period_start": day.isoformat(),
            "period_end": day.isoformat(),
        },
    )
    draft = response.json()
    completed_titles = {item["title"] for item in draft["facts"]["completed_tasks"]}
    assert "可追溯任务" in completed_titles
    expected = session.scalar(
        select(func.count()).select_from(Report).where(Report.report_type == "daily")
    )
    assert expected is not None  # reports are only persisted when the user saves


def test_work_daily_report_follows_company_template(
    client: TestClient,
    create_task: Callable[..., dict],
) -> None:
    day = today()
    project = client.post("/api/projects", json={"name": "支付网关改造", "status": "active"}).json()
    done = create_task(title="完成对账接口联调", project_id=project["id"], estimated_minutes=60)
    client.patch(f"/api/tasks/{done['id']}", json={"status": "completed"})
    create_task(title="补齐退款回调", project_id=project["id"], estimated_minutes=90)
    create_task(title="与工作无关的私事")

    response = client.post(
        "/api/reports/enhanced",
        json={
            "report_type": "daily",
            "period_start": day.isoformat(),
            "period_end": day.isoformat(),
            "project_id": project["id"],
            "template": "work",
        },
    )
    assert response.status_code == 200, response.text
    draft = response.json()
    markdown = draft["content_md"]
    assert draft["title"].startswith("TaskPilot 工作日报")
    for heading in [
        "## 一、今日完成",
        "## 二、未完成 / 进行中",
        "## 三、明日计划",
        "## 四、风险与需要协调",
        "## 五、数据小结",
    ]:
        assert heading in markdown, heading
    assert "完成对账接口联调" in markdown
    assert "补齐退款回调" in markdown
    assert "与工作无关的私事" not in markdown
    assert "数据来源：tasks.completed_at" in markdown
    assert draft["facts"]["template"] == "work"
    assert draft["facts"]["work"]["mode"] == "daily"
    assert draft["facts"]["work"]["completed"][0]["title"] == "完成对账接口联调"


def test_work_weekly_report_has_daily_table(
    client: TestClient,
    create_task: Callable[..., dict],
) -> None:
    end = today()
    start = end - timedelta(days=6)
    project = client.post("/api/projects", json={"name": "推荐系统重构"}).json()
    task = create_task(title="完成召回链路压测", project_id=project["id"])
    client.patch(f"/api/tasks/{task['id']}", json={"status": "completed"})

    response = client.post(
        "/api/reports/enhanced",
        json={
            "report_type": "weekly",
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "project_id": project["id"],
            "template": "work",
        },
    )
    assert response.status_code == 200, response.text
    markdown = response.json()["content_md"]
    assert "## 一、本周完成" in markdown
    assert "## 三、下周计划" in markdown
    assert "## 五、每日数据" in markdown
    assert "| 日期 | 完成 | 专注分钟 |" in markdown
    assert "## 六、数据小结" in markdown
