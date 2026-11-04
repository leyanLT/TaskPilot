import type {
  ActionStatus,
  ActionType,
  AssistantMessage,
  AssistantStreamEvent,
  AssistantStreamPhase,
  AssistantTurn,
  BreakdownDraft,
  ConfirmResult,
  PendingAction,
  PlanDraft,
  ReportDraft,
  TaskChanges,
  TaskDraft,
  TaskPriority,
  TaskStatus,
} from '../types'
import { ApiError, buildApiUrl, request } from './http'
import {
  mapBreakdown,
  mapPlanDraft,
  mapReportDraft,
  mapTask,
  mapTaskDraft,
  type BreakdownDto,
  type PlanDraftDto,
  type ReportDraftDto,
  type TaskDto,
  type TaskDraftDto,
} from './mappers'

interface TaskChangesDto {
  title: string | null
  description: string | null
  due_at: string | null
  priority: TaskPriority | null
  estimated_minutes: number | null
  project_id: string | null
  project_name: string | null
  changed_fields: string[]
}

interface PendingActionDto {
  id: string
  action_type: ActionType
  status: ActionStatus
  summary: string
  proposed_task: TaskDraftDto | null
  proposed_tasks: TaskDraftDto[]
  target_task: TaskDto | null
  target_tasks: TaskDto[]
  changes: TaskChangesDto | null
  proposed_breakdown: BreakdownDto | null
  proposed_plan: PlanDraftDto | null
  proposed_report: ReportDraftDto | null
  proposed_replan?: Record<string, unknown> | null
  proposed_project?: Record<string, unknown> | null
  created_at: string
  expires_at: string
}

interface CandidateDto {
  id: string
  title: string
  due_at: string | null
  status: TaskStatus
}

interface AssistantMessageDto {
  id: string
  role: 'user' | 'assistant'
  content: string
  action: PendingActionDto | null
  candidates: CandidateDto[]
  prompt_version: string | null
  created_at: string
}

interface AssistantTurnDto {
  user_message: AssistantMessageDto
  assistant_message: AssistantMessageDto
}

interface HistoryDto {
  messages: AssistantMessageDto[]
}

interface ConfirmResultDto {
  action_id: string
  status: ActionStatus
  message: string
  task: TaskDto | null
  affected_tasks: TaskDto[]
  report_id: string | null
  plan_date: string | null
}

interface ErrorEnvelope {
  error?: {
    code?: string
    message?: string
  }
}

interface StreamOptions {
  selectedTaskId?: string
  sourceMessageId?: string
  signal?: AbortSignal
}

function mapTaskDraftFromDto(dto: TaskDraftDto): TaskDraft {
  return mapTaskDraft(dto)
}

function mapChanges(dto: TaskChangesDto): TaskChanges {
  return {
    title: dto.title,
    description: dto.description,
    dueAt: dto.due_at,
    priority: dto.priority,
    estimatedMinutes: dto.estimated_minutes,
    projectId: dto.project_id,
    projectName: dto.project_name,
    changedFields: dto.changed_fields,
  }
}

function mapAction(dto: PendingActionDto): PendingAction {
  return {
    id: dto.id,
    actionType: dto.action_type,
    status: dto.status,
    summary: dto.summary,
    proposedTask: dto.proposed_task ? mapTaskDraftFromDto(dto.proposed_task) : null,
    proposedTasks: dto.proposed_tasks.map(mapTaskDraftFromDto),
    targetTask: dto.target_task ? mapTask(dto.target_task) : null,
    targetTasks: dto.target_tasks.map(mapTask),
    changes: dto.changes ? mapChanges(dto.changes) : null,
    proposedBreakdown: dto.proposed_breakdown
      ? mapBreakdown(dto.proposed_breakdown)
      : null,
    proposedPlan: dto.proposed_plan ? mapPlanDraft(dto.proposed_plan) : null,
    proposedReport: dto.proposed_report
      ? mapReportDraft(dto.proposed_report)
      : null,
    proposedReplan: dto.proposed_replan ?? null,
    proposedProject: dto.proposed_project ?? null,
    createdAt: dto.created_at,
    expiresAt: dto.expires_at,
  }
}

function mapMessage(dto: AssistantMessageDto): AssistantMessage {
  return {
    id: dto.id,
    role: dto.role,
    content: dto.content,
    action: dto.action ? mapAction(dto.action) : null,
    candidates: dto.candidates.map((candidate) => ({
      id: candidate.id,
      title: candidate.title,
      dueAt: candidate.due_at,
      status: candidate.status,
    })),
    promptVersion: dto.prompt_version,
    createdAt: dto.created_at,
  }
}

async function throwResponseError(response: Response): Promise<never> {
  const text = await response.text()
  let payload: ErrorEnvelope = {}
  if (text) {
    try {
      payload = JSON.parse(text) as ErrorEnvelope
    } catch {
      throw new ApiError(
        '服务器返回了无法解析的响应。',
        'INVALID_RESPONSE',
        response.status,
      )
    }
  }
  throw new ApiError(
    payload.error?.message || `请求失败（HTTP ${response.status}）。`,
    payload.error?.code || 'REQUEST_FAILED',
    response.status,
  )
}

function parseEventBlock(block: string): { event: string; data: string } | null {
  let event = 'message'
  const dataLines: string[] = []
  for (const line of block.split('\n')) {
    if (!line || line.startsWith(':')) {
      continue
    }
    if (line.startsWith('event:')) {
      event = line.slice('event:'.length).trim()
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice('data:'.length).trimStart())
    }
  }
  if (dataLines.length === 0) {
    return null
  }
  return { event, data: dataLines.join('\n') }
}

function mapStreamEvent(event: string, data: string): AssistantStreamEvent | null {
  let payload: unknown
  try {
    payload = JSON.parse(data)
  } catch {
    throw new ApiError('流式响应格式错误。', 'INVALID_RESPONSE', 200)
  }
  if (!payload || typeof payload !== 'object') {
    return null
  }
  const record = payload as Record<string, unknown>
  if (event === 'started') {
    const userMessage = record.user_message as AssistantMessageDto | undefined
    if (!userMessage) {
      return null
    }
    return {
      type: 'started',
      userMessage: mapMessage(userMessage),
      promptVersion:
        typeof record.prompt_version === 'string' ? record.prompt_version : null,
    }
  }
  if (event === 'status') {
    const phase = record.phase
    if (
      phase === 'thinking' ||
      phase === 'using_tools' ||
      phase === 'preparing_action' ||
      phase === 'composing'
    ) {
      return { type: 'status', phase: phase as AssistantStreamPhase }
    }
    return null
  }
  if (event === 'token' && typeof record.delta === 'string') {
    return { type: 'token', delta: record.delta }
  }
  if (event === 'done') {
    const assistantMessage = record.assistant_message as
      | AssistantMessageDto
      | undefined
    if (!assistantMessage) {
      return null
    }
    return { type: 'done', assistantMessage: mapMessage(assistantMessage) }
  }
  if (event === 'error') {
    const error = record.error as { code?: unknown; message?: unknown } | undefined
    return {
      type: 'error',
      code: typeof error?.code === 'string' ? error.code : 'AI_UPSTREAM_ERROR',
      message:
        typeof error?.message === 'string'
          ? error.message
          : 'AI 服务暂时不可用，请稍后重试。',
    }
  }
  return null
}

async function* readSse(response: Response): AsyncGenerator<AssistantStreamEvent> {
  if (!response.body) {
    throw new ApiError('流式响应为空。', 'INVALID_RESPONSE', response.status)
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) {
        buffer += decoder.decode()
        break
      }
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
      let boundary = buffer.indexOf('\n\n')
      while (boundary >= 0) {
        const block = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        const parsed = parseEventBlock(block)
        if (parsed) {
          const event = mapStreamEvent(parsed.event, parsed.data)
          if (event) {
            yield event
          }
        }
        boundary = buffer.indexOf('\n\n')
      }
    }

    const parsed = parseEventBlock(buffer)
    if (parsed) {
      const event = mapStreamEvent(parsed.event, parsed.data)
      if (event) {
        yield event
      }
    }
  } finally {
    reader.releaseLock()
  }
}

export const assistantApi = {
  async history(limit = 50): Promise<AssistantMessage[]> {
    const dto = await request<HistoryDto>(`/assistant/history?limit=${limit}`)
    return dto.messages.map(mapMessage)
  },

  async sendMessage(
    message: string,
    options: StreamOptions = {},
  ): Promise<AssistantTurn> {
    const body: Record<string, unknown> = { message }
    if (options.selectedTaskId) {
      body.selected_task_id = options.selectedTaskId
    }
    if (options.sourceMessageId) {
      body.source_message_id = options.sourceMessageId
    }
    const dto = await request<AssistantTurnDto>('/assistant/messages', {
      method: 'POST',
      body: JSON.stringify(body),
    })
    return {
      userMessage: mapMessage(dto.user_message),
      assistantMessage: mapMessage(dto.assistant_message),
    }
  },

  async *streamMessage(message: string, options: StreamOptions = {}) {
    const body: Record<string, unknown> = { message }
    if (options.selectedTaskId) {
      body.selected_task_id = options.selectedTaskId
    }
    if (options.sourceMessageId) {
      body.source_message_id = options.sourceMessageId
    }

    const headers = new Headers()
    headers.set('Accept', 'text/event-stream')
    headers.set('Content-Type', 'application/json')

    const response = await fetch(buildApiUrl('/assistant/messages/stream'), {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
      signal: options.signal,
    })
    if (!response.ok) {
      await throwResponseError(response)
    }
    const contentType = response.headers.get('content-type') || ''
    if (!contentType.includes('text/event-stream')) {
      await throwResponseError(response)
    }
    yield* readSse(response)
  },

  async confirm(
    actionId: string,
    confirm: boolean,
    payloadOverrides?: Record<string, unknown>,
  ): Promise<ConfirmResult> {
    const body: Record<string, unknown> = {
      action_id: actionId,
      confirm,
    }
    if (payloadOverrides !== undefined) {
      body.payload_overrides = payloadOverrides
    }
    const dto = await request<ConfirmResultDto>('/assistant/confirm', {
      method: 'POST',
      body: JSON.stringify(body),
    })
    return {
      actionId: dto.action_id,
      status: dto.status,
      message: dto.message,
      task: dto.task ? mapTask(dto.task) : null,
      affectedTasks: dto.affected_tasks.map(mapTask),
      reportId: dto.report_id,
      planDate: dto.plan_date,
    }
  },
}

export function toBreakdownOverrides(draft: BreakdownDraft): Record<string, unknown> {
  return {
    goal: draft.goal,
    project_id: draft.projectId,
    tasks: draft.tasks.map((task) => ({
      title: task.title,
      description: task.description,
      priority: task.priority,
      estimated_minutes: task.estimatedMinutes,
      due_at: task.dueAt,
      subtasks: task.subtasks.map((subtask) => ({
        title: subtask.title,
        description: subtask.description,
        priority: subtask.priority,
        estimated_minutes: subtask.estimatedMinutes,
        due_at: subtask.dueAt,
      })),
    })),
  }
}

export function toPlanOverrides(plan: PlanDraft): Record<string, unknown> {
  return {
    plan_date: plan.planDate,
    available_minutes: plan.availableMinutes,
    items: plan.items.map((item) => ({
      task_id: item.taskId,
      start_at: item.startAt,
      end_at: item.endAt,
      note: item.note,
    })),
  }
}

export function toReportOverrides(report: ReportDraft): Record<string, unknown> {
  return {
    report_type: report.reportType,
    title: report.title,
    period_start: report.periodStart,
    period_end: report.periodEnd,
    project_id: report.projectId,
    content_md: report.contentMd,
    facts: report.facts,
    ai_used: report.aiUsed,
  }
}
