"""Domain exceptions and the single API error response shape."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("taskpilot.errors")


class AppError(Exception):
    """Base for expected application errors that are safe to expose."""

    status_code = 500
    code = "INTERNAL_ERROR"
    default_message = "服务器内部错误，请稍后重试。"

    def __init__(self, message: str | None = None, details: Any = None) -> None:
        super().__init__(message or self.default_message)
        self.message = message or self.default_message
        self.details = details


class TaskNotFoundError(AppError):
    status_code = 404
    code = "TASK_NOT_FOUND"
    default_message = "任务不存在。"


class TaskAlreadyCompletedError(AppError):
    status_code = 409
    code = "TASK_ALREADY_COMPLETED"
    default_message = "该任务已经是已完成状态。"


class TaskHasUnfinishedSubtasksError(AppError):
    status_code = 409
    code = "TASK_HAS_UNFINISHED_SUBTASKS"
    default_message = "还有未完成的子任务，完成全部子任务后才能完成父任务。"


class TaskHasSubtasksError(AppError):
    status_code = 409
    code = "TASK_HAS_SUBTASKS"
    default_message = "该任务包含子任务，删除前需要明确确认影响范围。"


class TaskHierarchyError(AppError):
    status_code = 409
    code = "TASK_HIERARCHY_INVALID"
    default_message = "任务层级不合法：当前只支持父任务与子任务两级结构。"


class InvalidSubtaskOrderError(AppError):
    status_code = 409
    code = "INVALID_SUBTASK_ORDER"
    default_message = "子任务顺序数据不完整，请刷新后重试。"


class ProjectNotFoundError(AppError):
    status_code = 404
    code = "PROJECT_NOT_FOUND"
    default_message = "项目不存在。"


class ProjectArchivedError(AppError):
    status_code = 409
    code = "PROJECT_ARCHIVED"
    default_message = "项目已归档，不能把新任务加入该项目。请先恢复项目。"


class InvalidDateRangeError(AppError):
    status_code = 422
    code = "INVALID_DATE_RANGE"
    default_message = "截止日期不能早于开始日期。"


class PlanNotFoundError(AppError):
    status_code = 404
    code = "PLAN_NOT_FOUND"
    default_message = "这一天还没有计划。"


class PlanConflictError(AppError):
    status_code = 409
    code = "PLAN_CONFLICT"
    default_message = "计划安排不可用，请检查任务与时间。"


class NotificationNotFoundError(AppError):
    status_code = 404
    code = "NOTIFICATION_NOT_FOUND"
    default_message = "提醒不存在。"


class ReportNotFoundError(AppError):
    status_code = 404
    code = "REPORT_NOT_FOUND"
    default_message = "报告不存在。"


class AssistantMessageNotFoundError(AppError):
    status_code = 404
    code = "CHAT_MESSAGE_NOT_FOUND"
    default_message = "对话消息不存在。"


class AssistantCandidateMismatchError(AppError):
    status_code = 409
    code = "INVALID_CANDIDATE"
    default_message = "候选项已失效，请重新发起操作。"


class PendingActionNotFoundError(AppError):
    status_code = 404
    code = "ACTION_NOT_FOUND"
    default_message = "待确认操作不存在。"


class PendingActionConflictError(AppError):
    status_code = 409
    code = "ACTION_CONFLICT"
    default_message = "该操作当前不可执行。"


class PendingActionExpiredError(AppError):
    status_code = 410
    code = "ACTION_EXPIRED"
    default_message = "该操作已过期，请重新发起。"


class InvalidActionPayloadError(AppError):
    status_code = 422
    code = "INVALID_ACTION_PAYLOAD"
    default_message = "待确认操作的数据无效。"


class DatabaseOperationError(AppError):
    status_code = 500
    code = "DATABASE_ERROR"
    default_message = "数据操作失败，请稍后重试。"


# V2.0 -----------------------------------------------------------------------


class DependencySelfError(AppError):
    status_code = 422
    code = "DEPENDENCY_SELF"
    default_message = "任务不能依赖自己。"


class DependencyDuplicateError(AppError):
    status_code = 409
    code = "DEPENDENCY_DUPLICATE"
    default_message = "这个前置任务已经添加过了。"


class DependencyCycleError(AppError):
    status_code = 409
    code = "DEPENDENCY_CYCLE"
    default_message = "添加后会形成循环依赖，请调整任务的先后顺序。"


class DependencyScopeError(AppError):
    status_code = 409
    code = "DEPENDENCY_SCOPE"
    default_message = "依赖任务必须属于同一个项目（或都不属于任何项目）。"


class TaskBlockedError(AppError):
    status_code = 409
    code = "TASK_BLOCKED"
    default_message = "前置任务还没有完成，暂时不能完成这个任务。"


class RecurrenceNotFoundError(AppError):
    status_code = 404
    code = "RECURRENCE_NOT_FOUND"
    default_message = "重复任务规则不存在。"


class InvalidRecurrenceError(AppError):
    status_code = 422
    code = "INVALID_RECURRENCE"
    default_message = "重复任务规则无效，请检查日期与重复方式。"


class FocusNotFoundError(AppError):
    status_code = 404
    code = "FOCUS_NOT_FOUND"
    default_message = "专注会话不存在。"


class FocusConflictError(AppError):
    status_code = 409
    code = "FOCUS_CONFLICT"
    default_message = "专注状态冲突，请刷新后重试。"


class TimeBlockNotFoundError(AppError):
    status_code = 404
    code = "TIME_BLOCK_NOT_FOUND"
    default_message = "时间块不存在。"


class TimeBlockConflictError(AppError):
    status_code = 409
    code = "TIME_BLOCK_CONFLICT"
    default_message = "时间块与已有安排冲突，请调整时间。"


class PlanVersionConflictError(AppError):
    status_code = 409
    code = "PLAN_VERSION_CONFLICT"
    default_message = "计划在确认前已经发生变化，请重新生成方案。"


class InsightNotFoundError(AppError):
    status_code = 404
    code = "INSIGHT_NOT_FOUND"
    default_message = "这条提醒已经不存在。"


class ReportExportError(AppError):
    status_code = 503
    code = "REPORT_EXPORT_UNAVAILABLE"
    default_message = "当前环境缺少导出所需的组件。"


class AINotConfiguredError(AppError):
    status_code = 503
    code = "AI_NOT_CONFIGURED"
    default_message = "AI 助手尚未配置，请设置 DEEPSEEK_API_KEY。手动任务管理仍可正常使用。"


class AITimeoutError(AppError):
    status_code = 504
    code = "AI_TIMEOUT"
    default_message = "AI 服务响应超时，请稍后重试。手动任务管理不受影响。"


class AIAuthenticationError(AppError):
    status_code = 502
    code = "AI_AUTH_ERROR"
    default_message = "AI 服务鉴权失败，请检查 API Key 配置。"


class AIUpstreamError(AppError):
    status_code = 502
    code = "AI_UPSTREAM_ERROR"
    default_message = "AI 服务暂时不可用，请稍后重试。手动任务管理不受影响。"


class AIServiceUnavailableError(AppError):
    status_code = 503
    code = "AI_UNAVAILABLE"
    default_message = "AI 服务暂时不可用，请稍后重试。手动任务管理不受影响。"


class AIInvalidOutputError(AppError):
    status_code = 502
    code = "AI_INVALID_OUTPUT"
    default_message = "AI 返回了无法处理的结果，请重试。"


def error_body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"error": error}


def register_exception_handlers(app: object) -> None:
    """Register handlers on the FastAPI app (typed loosely to avoid a cycle)."""

    from fastapi import FastAPI

    assert isinstance(app, FastAPI)

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        if exc.status_code >= 500:
            logger.warning("Application error on %s: %s", request.url.path, exc.code)
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [
            {
                "field": ".".join(str(part) for part in item.get("loc", ())),
                "message": item.get("msg", "输入无效"),
                "type": item.get("type", "value_error"),
            }
            for item in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=error_body("VALIDATION_ERROR", "请求参数校验失败。", details),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR"
        message = str(exc.detail) if exc.detail else "请求失败。"
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(code, message),
        )

    @app.exception_handler(SQLAlchemyError)
    async def handle_database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.exception("Unhandled database error on %s", request.url.path)
        return JSONResponse(
            status_code=500,
            content=error_body("DATABASE_ERROR", "数据操作失败，请稍后重试。"),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error on %s", request.url.path)
        return JSONResponse(
            status_code=500,
            content=error_body("INTERNAL_ERROR", "服务器内部错误，请稍后重试。"),
        )
