"""Report generation, factual scoping, AI fallback, persistence, and export."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.schemas import ReportGenerateRequest
from app.services.report_service import AI_FALLBACK, ReportService
from fastapi.testclient import TestClient

TIMEZONE = ZoneInfo("Asia/Shanghai")


def make_task(client: TestClient, title: str, **overrides: object) -> dict:
    payload: dict[str, object] = {"title": title}
    payload.update(overrides)
    response = client.post("/api/tasks", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def completed_task(client: TestClient, title: str, **overrides: object) -> dict:
    task = make_task(client, title, **overrides)
    response = client.patch(f"/api/tasks/{task['id']}", json={"status": "completed"})
    assert response.status_code == 200
    return response.json()


def test_daily_report_uses_completed_at_scope(client: TestClient, session) -> None:
    done = completed_task(client, "今天完成的事")
    make_task(client, "还没做的事")
    service = ReportService(
        session,
        timezone=TIMEZONE,
        narrative_writer=None,
    )

    today = datetime.now(TIMEZONE).date()
    draft = service.generate(
        ReportGenerateRequest(report_type="daily"),
        use_ai=False,
    )
    assert draft.report_type.value == "daily"
    assert draft.title.startswith(today.isoformat())
    assert "统计范围" in draft.content_md
    assert "今日已完成工作" in draft.content_md
    assert "今天完成的事" in draft.content_md
    assert "还没做的事" in draft.content_md  # pending task is listed as unfinished
    assert draft.ai_used is False
    assert AI_FALLBACK in draft.content_md
    facts = draft.facts
    assert facts["counts"]["completed"] >= 1
    assert any(item["title"] == "今天完成的事" for item in facts["completed_tasks"])
    assert done["completed_at"] is not None

    # A task completed now must not appear as completed in a 2020 report.
    past_draft = service.generate(
        ReportGenerateRequest(
            report_type="daily",
            period_start=datetime(2020, 1, 1, tzinfo=TIMEZONE),
            period_end=datetime(2020, 1, 2, tzinfo=TIMEZONE),
        ),
        use_ai=False,
    )
    assert past_draft.facts["counts"]["completed"] == 0
    assert "统计期内没有已完成任务" in past_draft.content_md


def test_weekly_report_lists_projects_and_next_week_plan(client: TestClient, session) -> None:
    project = client.post(
        "/api/projects",
        json={"name": "周报项目", "status": "active"},
    ).json()
    completed_task(client, "周报任务", project_id=project["id"])
    upcoming = make_task(
        client,
        "下周要做的任务",
        due_at=(datetime.now(TIMEZONE) + timedelta(days=10)).isoformat(),
    )
    assert upcoming["id"]

    service = ReportService(session, timezone=TIMEZONE, narrative_writer=None)
    draft = service.generate(ReportGenerateRequest(report_type="weekly"), use_ai=False)
    assert "工作周报" in draft.title
    assert "重点项目进度" in draft.content_md
    assert "周报项目" in draft.content_md
    assert any(item["title"] == "下周要做的任务" for item in draft.facts["upcoming_tasks"])


def test_project_report_requires_project_and_reports_progress(client: TestClient, session) -> None:
    project = client.post(
        "/api/projects",
        json={"name": "报告项目", "status": "active"},
    ).json()
    done = make_task(client, "已完成任务", project_id=project["id"])
    client.patch(f"/api/tasks/{done['id']}", json={"status": "completed"})
    make_task(client, "待办任务", project_id=project["id"])

    missing = client.post("/api/reports/generate", json={"report_type": "project"})
    assert missing.status_code == 422

    response = client.post(
        "/api/reports/generate",
        json={"report_type": "project", "project_id": project["id"]},
    )
    assert response.status_code == 200, response.text
    draft = response.json()
    assert draft["project_name"] == "报告项目"
    assert "项目基本信息" in draft["content_md"]
    assert "整体进度" in draft["content_md"]
    assert draft["facts"]["counts"]["completed"] == 1
    assert draft["facts"]["project"]["name"] == "报告项目"


def test_report_generate_does_not_save(client: TestClient) -> None:
    before = client.get("/api/reports").json()
    response = client.post("/api/reports/generate", json={"report_type": "daily"})
    assert response.status_code == 200
    after = client.get("/api/reports").json()
    assert len(after) == len(before)


def test_save_edit_list_and_delete_report(client: TestClient) -> None:
    draft = client.post("/api/reports/generate", json={"report_type": "daily"}).json()
    saved = client.post(
        "/api/reports",
        json={
            "report_type": draft["report_type"],
            "title": draft["title"],
            "period_start": draft["period_start"],
            "period_end": draft["period_end"],
            "content_md": draft["content_md"],
            "facts": draft["facts"],
            "ai_used": draft["ai_used"],
        },
    )
    assert saved.status_code == 201, saved.text
    report = saved.json()
    assert report["title"] == draft["title"]

    listed = client.get("/api/reports").json()
    assert [item["id"] for item in listed] == [report["id"]]

    edited = client.patch(
        f"/api/reports/{report['id']}",
        json={"content_md": "# 修改后的报告\n\n- 已人工修订"},
    )
    assert edited.status_code == 200
    assert "已人工修订" in edited.json()["content_md"]

    exported = client.get(f"/api/reports/{report['id']}/markdown")
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/markdown")
    assert "attachment" in exported.headers["content-disposition"]
    assert "已人工修订" in exported.text

    deleted = client.delete(f"/api/reports/{report['id']}")
    assert deleted.status_code == 204
    assert client.get(f"/api/reports/{report['id']}").status_code == 404


def test_ai_narrative_is_used_but_facts_stay_deterministic(client: TestClient, session) -> None:
    completed_task(client, "AI 报告任务")
    prompts: list[str] = []

    def writer(prompt: str) -> str:
        prompts.append(prompt)
        return "存在的问题：\n- 任务集中在少数项目\n后续建议：\n- 保持每日计划"

    service = ReportService(session, timezone=TIMEZONE, narrative_writer=writer)
    draft = service.generate(ReportGenerateRequest(report_type="daily"), use_ai=True)
    assert prompts and "事实 JSON" in prompts[0]
    assert draft.ai_used is True
    assert "任务集中在少数项目" in draft.content_md
    assert "保持每日计划" in draft.content_md
    assert draft.facts["counts"]["completed"] >= 1
    assert any(item["title"] == "AI 报告任务" for item in draft.facts["completed_tasks"])


def test_ai_failure_falls_back_without_losing_facts(client: TestClient, session) -> None:
    completed_task(client, "失败回退任务")

    def broken(prompt: str) -> str:
        raise RuntimeError("upstream boom")

    service = ReportService(session, timezone=TIMEZONE, narrative_writer=broken)
    draft = service.generate(ReportGenerateRequest(report_type="daily"), use_ai=True)
    assert draft.ai_used is False
    assert AI_FALLBACK in draft.content_md
    assert any(item["title"] == "失败回退任务" for item in draft.facts["completed_tasks"])


def test_empty_dataset_is_reported_not_invented(client: TestClient) -> None:
    response = client.post(
        "/api/reports/generate",
        json={
            "report_type": "daily",
            "period_start": datetime.combine(
                datetime(2020, 5, 1).date(), time.min, tzinfo=TIMEZONE
            ).isoformat(),
            "period_end": datetime.combine(
                datetime(2020, 5, 2).date(), time.min, tzinfo=TIMEZONE
            ).isoformat(),
        },
    )
    assert response.status_code == 200
    draft = response.json()
    assert draft["facts"]["counts"]["completed"] == 0
    assert "没有已完成任务" in draft["content_md"]
    assert "没有逾期" in draft["content_md"]
