import { buildApiUrl, request } from './http'
import type {
  CalendarRange,
  DependencyLink,
  FocusSession,
  FocusStats,
  InsightList,
  Preferences,
  RecurrenceInput,
  RecurrenceRule,
  ReplanBlock,
  ReplanDraft,
  TaskDependencies,
  TimeBlock,
} from '../types/v2'

function query(params: Record<string, string | undefined>): string {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value) {
      search.set(key, value)
    }
  })
  const encoded = search.toString()
  return encoded ? `?${encoded}` : ''
}

// -- dependencies -------------------------------------------------------------

interface DependencyDto {
  id: string
  task_id: string
  depends_on_task_id: string
  depends_on_title: string
  depends_on_status: 'pending' | 'completed'
  created_at: string
}

interface DependenciesDto {
  task_id: string
  is_blocked: boolean
  depends_on: DependencyDto[]
  blocks: DependencyDto[]
}

function mapDependency(dto: DependencyDto): DependencyLink {
  return {
    id: dto.id,
    taskId: dto.task_id,
    dependsOnTaskId: dto.depends_on_task_id,
    dependsOnTitle: dto.depends_on_title,
    dependsOnStatus: dto.depends_on_status,
    createdAt: dto.created_at,
  }
}

export const dependencyApi = {
  async get(taskId: string): Promise<TaskDependencies> {
    const dto = await request<DependenciesDto>(`/dependencies/${taskId}`)
    return {
      taskId: dto.task_id,
      isBlocked: dto.is_blocked,
      dependsOn: dto.depends_on.map(mapDependency),
      blocks: dto.blocks.map(mapDependency),
    }
  },
  async add(taskId: string, dependsOnTaskId: string): Promise<void> {
    await request<DependencyDto>(`/dependencies/${taskId}`, {
      method: 'POST',
      body: JSON.stringify({ depends_on_task_id: dependsOnTaskId }),
    })
  },
  async remove(taskId: string, dependencyId: string): Promise<void> {
    await request<void>(`/dependencies/${taskId}/${dependencyId}`, { method: 'DELETE' })
  },
  async summary(): Promise<Record<string, string[]>> {
    return request<Record<string, string[]>>('/dependencies/summary')
  },
}

// -- recurring rules ----------------------------------------------------------

interface RecurrenceDto {
  id: string
  title: string
  description: string | null
  project_id: string | null
  priority: RecurrenceRule['priority']
  estimated_minutes: number | null
  frequency: RecurrenceRule['frequency']
  interval: number
  weekdays: number[] | null
  start_date: string
  end_date: string | null
  due_time: string | null
  timezone: string
  paused: boolean
  next_occurrence: string | null
  generated_count: number
  completed_count: number
  pending_count: number
  created_at: string
  updated_at: string
}

function mapRecurrence(dto: RecurrenceDto): RecurrenceRule {
  return {
    id: dto.id,
    title: dto.title,
    description: dto.description,
    projectId: dto.project_id,
    priority: dto.priority,
    estimatedMinutes: dto.estimated_minutes,
    frequency: dto.frequency,
    interval: dto.interval,
    weekdays: dto.weekdays,
    startDate: dto.start_date,
    endDate: dto.end_date,
    dueTime: dto.due_time,
    timezone: dto.timezone,
    paused: dto.paused,
    nextOccurrence: dto.next_occurrence,
    generatedCount: dto.generated_count,
    completedCount: dto.completed_count,
    pendingCount: dto.pending_count,
    createdAt: dto.created_at,
    updatedAt: dto.updated_at,
  }
}

function recurrenceBody(input: Partial<RecurrenceInput>): Record<string, unknown> {
  const body: Record<string, unknown> = {}
  if (input.title !== undefined) body.title = input.title
  if (input.description !== undefined) body.description = input.description
  if (input.projectId !== undefined) body.project_id = input.projectId
  if (input.priority !== undefined) body.priority = input.priority
  if (input.estimatedMinutes !== undefined) body.estimated_minutes = input.estimatedMinutes
  if (input.frequency !== undefined) body.frequency = input.frequency
  if (input.interval !== undefined) body.interval = input.interval
  if (input.weekdays !== undefined) body.weekdays = input.weekdays
  if (input.startDate !== undefined) body.start_date = input.startDate
  if (input.endDate !== undefined) body.end_date = input.endDate
  if (input.dueTime !== undefined) body.due_time = input.dueTime
  return body
}

export const recurrenceApi = {
  async list(): Promise<RecurrenceRule[]> {
    const data = await request<RecurrenceDto[]>('/recurrences')
    return data.map(mapRecurrence)
  },
  async create(input: RecurrenceInput): Promise<RecurrenceRule> {
    return mapRecurrence(
      await request<RecurrenceDto>('/recurrences', {
        method: 'POST',
        body: JSON.stringify(recurrenceBody(input)),
      }),
    )
  },
  async update(ruleId: string, input: Partial<RecurrenceInput>): Promise<RecurrenceRule> {
    return mapRecurrence(
      await request<RecurrenceDto>(`/recurrences/${ruleId}`, {
        method: 'PATCH',
        body: JSON.stringify(recurrenceBody(input)),
      }),
    )
  },
  async setPaused(ruleId: string, paused: boolean): Promise<RecurrenceRule> {
    return mapRecurrence(
      await request<RecurrenceDto>(
        `/recurrences/${ruleId}/${paused ? 'pause' : 'resume'}`,
        { method: 'POST' },
      ),
    )
  },
  async remove(ruleId: string): Promise<void> {
    await request<void>(`/recurrences/${ruleId}`, { method: 'DELETE' })
  },
}

// -- focus --------------------------------------------------------------------

interface FocusDto {
  id: string
  task_id: string
  task_title: string
  task_estimated_minutes: number | null
  status: FocusSession['status']
  mode: FocusSession['mode']
  planned_minutes: number | null
  elapsed_seconds: number
  accumulated_seconds: number
  target_seconds: number | null
  remaining_seconds: number | null
  started_at: string
  last_resumed_at: string | null
  ended_at: string | null
  synced_at: string
}

interface FocusStatsDto {
  today: string
  today_seconds: number
  week_seconds: number
  session_count: number
  by_day: Array<{ date: string; seconds: number }>
  by_task: Array<{ task_id: string; title: string; seconds: number }>
}

function mapFocus(dto: FocusDto): FocusSession {
  return {
    id: dto.id,
    taskId: dto.task_id,
    taskTitle: dto.task_title,
    taskEstimatedMinutes: dto.task_estimated_minutes,
    status: dto.status,
    mode: dto.mode,
    plannedMinutes: dto.planned_minutes,
    elapsedSeconds: dto.elapsed_seconds,
    accumulatedSeconds: dto.accumulated_seconds,
    targetSeconds: dto.target_seconds,
    remainingSeconds: dto.remaining_seconds,
    startedAt: dto.started_at,
    lastResumedAt: dto.last_resumed_at,
    endedAt: dto.ended_at,
    syncedAt: dto.synced_at,
  }
}

export const focusApi = {
  async active(): Promise<FocusSession | null> {
    const dto = await request<FocusDto | null>('/focus/active')
    return dto ? mapFocus(dto) : null
  },
  async start(taskId: string, plannedMinutes: number, mode: 'free' | 'pomodoro'): Promise<FocusSession> {
    return mapFocus(
      await request<FocusDto>('/focus/start', {
        method: 'POST',
        body: JSON.stringify({
          task_id: taskId,
          planned_minutes: plannedMinutes,
          mode,
        }),
      }),
    )
  },
  async pause(sessionId: string): Promise<FocusSession> {
    return mapFocus(
      await request<FocusDto>(`/focus/${sessionId}/pause`, { method: 'POST' }),
    )
  },
  async resume(sessionId: string): Promise<FocusSession> {
    return mapFocus(
      await request<FocusDto>(`/focus/${sessionId}/resume`, { method: 'POST' }),
    )
  },
  async stop(sessionId: string): Promise<FocusSession> {
    return mapFocus(
      await request<FocusDto>(`/focus/${sessionId}/stop`, { method: 'POST' }),
    )
  },
  async stats(): Promise<FocusStats> {
    const dto = await request<FocusStatsDto>('/focus/stats')
    return {
      today: dto.today,
      todaySeconds: dto.today_seconds,
      weekSeconds: dto.week_seconds,
      sessionCount: dto.session_count,
      byDay: dto.by_day,
      byTask: dto.by_task.map((item) => ({
        taskId: item.task_id,
        title: item.title,
        seconds: item.seconds,
      })),
    }
  },
}

// -- calendar -----------------------------------------------------------------

interface TimeBlockDto {
  id: string
  plan_id: string
  plan_date: string
  task_id: string
  task_title: string
  task_status: 'pending' | 'completed'
  start_at: string
  end_at: string
  note: string | null
  position: number
}

interface CalendarDayDto {
  date: string
  available_minutes: number
  planned_minutes: number
  blocks: TimeBlockDto[]
  due_tasks: Array<{
    id: string
    title: string
    status: 'pending' | 'completed'
    priority: CalendarRange['days'][number]['dueTasks'][number]['priority']
    due_at: string | null
    project_id: string | null
    is_blocked: boolean
    recurrence_rule_id: string | null
  }>
}

function mapBlock(dto: TimeBlockDto): TimeBlock {
  return {
    id: dto.id,
    planId: dto.plan_id,
    planDate: dto.plan_date,
    taskId: dto.task_id,
    taskTitle: dto.task_title,
    taskStatus: dto.task_status,
    startAt: dto.start_at,
    endAt: dto.end_at,
    note: dto.note,
    position: dto.position,
  }
}

export const calendarApi = {
  async range(start: string, end: string, projectId?: string): Promise<CalendarRange> {
    const dto = await request<{
      start: string
      end: string
      total_planned_minutes: number
      days: CalendarDayDto[]
    }>(`/calendar${query({ start, end, project_id: projectId })}`)
    return {
      start: dto.start,
      end: dto.end,
      totalPlannedMinutes: dto.total_planned_minutes,
      days: dto.days.map((day) => ({
        date: day.date,
        availableMinutes: day.available_minutes,
        plannedMinutes: day.planned_minutes,
        blocks: day.blocks.map(mapBlock),
        dueTasks: day.due_tasks.map((task) => ({
          id: task.id,
          title: task.title,
          status: task.status,
          priority: task.priority,
          dueAt: task.due_at,
          projectId: task.project_id,
          isBlocked: task.is_blocked,
          recurrenceRuleId: task.recurrence_rule_id,
        })),
      })),
    }
  },
  async createBlock(input: {
    planDate: string
    taskId: string
    startAt: string
    endAt: string
    note?: string | null
  }): Promise<TimeBlock> {
    return mapBlock(
      await request<TimeBlockDto>('/time-blocks', {
        method: 'POST',
        body: JSON.stringify({
          plan_date: input.planDate,
          task_id: input.taskId,
          start_at: input.startAt,
          end_at: input.endAt,
          note: input.note ?? null,
        }),
      }),
    )
  },
  async updateBlock(
    blockId: string,
    input: { startAt?: string; endAt?: string; note?: string | null },
  ): Promise<TimeBlock> {
    const body: Record<string, unknown> = {}
    if (input.startAt) body.start_at = input.startAt
    if (input.endAt) body.end_at = input.endAt
    if (input.note !== undefined) body.note = input.note
    return mapBlock(
      await request<TimeBlockDto>(`/time-blocks/${blockId}`, {
        method: 'PATCH',
        body: JSON.stringify(body),
      }),
    )
  },
  async deleteBlock(blockId: string): Promise<void> {
    await request<void>(`/time-blocks/${blockId}`, { method: 'DELETE' })
  },
}

// -- insights / replan / preferences ------------------------------------------

interface InsightDto {
  key: string
  code: string
  severity: 'high' | 'medium' | 'low'
  title: string
  reason: string
  suggestion: string
  task_ids: string[]
  task_titles: string[]
  project_id: string | null
  metric: Record<string, unknown>
}

export const insightApi = {
  async list(): Promise<InsightList> {
    const dto = await request<{
      generated_at: string
      items: InsightDto[]
      dismissed_count: number
    }>('/insights')
    return {
      generatedAt: dto.generated_at,
      dismissedCount: dto.dismissed_count,
      items: dto.items.map((item) => ({
        key: item.key,
        code: item.code,
        severity: item.severity,
        title: item.title,
        reason: item.reason,
        suggestion: item.suggestion,
        taskIds: item.task_ids,
        taskTitles: item.task_titles,
        projectId: item.project_id,
        metric: item.metric,
      })),
    }
  },
  async dismiss(key: string): Promise<void> {
    await request<void>('/insights/dismiss', {
      method: 'POST',
      body: JSON.stringify({ key }),
    })
  },
}

interface ReplanDto {
  plan_date: string
  available_minutes: number
  before: ReplanDraft['before']
  after: ReplanDraft['after']
  changes: Array<{
    kind: ReplanDraft['changes'][number]['kind']
    task_id: string
    title: string
    before_start: string | null
    after_start: string | null
  }>
  blocked_tasks: Array<{ task_id: string; title: string; blocked_by: string[] }>
  unscheduled: Array<{ task_id: string; title: string; blocked_by: string[] }>
  explanation: string[]
  plan_token: string
}

function mapReplan(dto: ReplanDto): ReplanDraft {
  return {
    planDate: dto.plan_date,
    availableMinutes: dto.available_minutes,
    before: dto.before,
    after: dto.after,
    changes: dto.changes.map((change) => ({
      kind: change.kind,
      taskId: change.task_id,
      title: change.title,
      beforeStart: change.before_start,
      afterStart: change.after_start,
    })),
    blockedTasks: dto.blocked_tasks.map((item) => ({
      taskId: item.task_id,
      title: item.title,
      blockedBy: item.blocked_by,
    })),
    unscheduled: dto.unscheduled.map((item) => ({
      taskId: item.task_id,
      title: item.title,
      blockedBy: item.blocked_by,
    })),
    explanation: dto.explanation,
    planToken: dto.plan_token,
  }
}

export const replanApi = {
  async preview(planDate: string, reason: string): Promise<ReplanDraft> {
    return mapReplan(
      await request<ReplanDto>('/replan/preview', {
        method: 'POST',
        body: JSON.stringify({ plan_date: planDate, reason }),
      }),
    )
  },
  async apply(
    planDate: string,
    blocks: ReplanBlock[],
    planToken: string,
    reason: string,
  ): Promise<void> {
    await request('/replan/apply', {
      method: 'POST',
      body: JSON.stringify({
        plan_date: planDate,
        blocks,
        plan_token: planToken,
        reason,
      }),
    })
  },
}

interface PreferencesDto {
  timezone: string
  daily_available_minutes: number
  workdays: number[]
  default_focus_minutes: number
  reminder_prefs: Record<string, unknown>
  updated_at: string
}

function mapPreferences(dto: PreferencesDto): Preferences {
  return {
    timezone: dto.timezone,
    dailyAvailableMinutes: dto.daily_available_minutes,
    workdays: dto.workdays,
    defaultFocusMinutes: dto.default_focus_minutes,
    reminderPrefs: dto.reminder_prefs,
    updatedAt: dto.updated_at,
  }
}

export const preferenceApi = {
  async get(): Promise<Preferences> {
    return mapPreferences(await request<PreferencesDto>('/preferences'))
  },
  async update(input: Partial<Preferences>): Promise<Preferences> {
    const body: Record<string, unknown> = {}
    if (input.timezone !== undefined) body.timezone = input.timezone
    if (input.dailyAvailableMinutes !== undefined) {
      body.daily_available_minutes = input.dailyAvailableMinutes
    }
    if (input.workdays !== undefined) body.workdays = input.workdays
    if (input.defaultFocusMinutes !== undefined) {
      body.default_focus_minutes = input.defaultFocusMinutes
    }
    return mapPreferences(
      await request<PreferencesDto>('/preferences', {
        method: 'PATCH',
        body: JSON.stringify(body),
      }),
    )
  },
}

export function reportDownloadUrl(reportId: string, format: 'docx' | 'pdf'): string {
  return buildApiUrl(`/reports/${reportId}/${format}`)
}
