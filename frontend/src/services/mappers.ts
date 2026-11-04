import type {
  Activity,
  ActivityAction,
  AppNotification,
  BreakdownDraft,
  BreakdownSubtaskDraft,
  Dashboard,
  DashboardCounts,
  NotificationList,
  Plan,
  PlanDraft,
  PlanItem,
  PrioritySuggestion,
  Project,
  ProjectStats,
  ProjectStatus,
  Report,
  ReportDraft,
  ReportFacts,
  ReportSummary,
  ReportType,
  Task,
  TaskDraft,
  TaskPriority,
  TaskStatus,
} from '../types'

export interface TaskDto {
  id: string
  title: string
  description: string | null
  status: TaskStatus
  due_at: string | null
  project_id: string | null
  parent_id: string | null
  priority: TaskPriority
  estimated_minutes: number | null
  position: number
  completed_at: string | null
  created_at: string
  updated_at: string
  subtask_count: number
  completed_subtask_count: number
}

export interface ProjectStatsDto {
  total_tasks: number
  completed_tasks: number
  pending_tasks: number
  overdue_tasks: number
  completion_rate: number
}

export interface ProjectDto {
  id: string
  name: string
  description: string | null
  status: ProjectStatus
  start_date: string | null
  due_date: string | null
  created_at: string
  updated_at: string
  stats: ProjectStatsDto
}

export interface ActivityDto {
  id: string
  task_id: string | null
  task_title: string | null
  project_id: string | null
  project_name: string | null
  action: ActivityAction
  field: string | null
  old_value: string | null
  new_value: string | null
  summary: string
  created_at: string
}

export interface PlanItemDto {
  id: string
  task_id: string
  task_title: string
  task_status: TaskStatus
  priority: TaskPriority
  estimated_minutes: number | null
  start_at: string
  end_at: string
  position: number
  note: string | null
}

export interface PlanDto {
  id: string
  plan_date: string
  timezone: string
  available_minutes: number
  planned_minutes: number
  items: PlanItemDto[]
  created_at: string
  updated_at: string
}

export interface NotificationDto {
  id: string
  type: AppNotification['type']
  task_id: string | null
  task_title: string | null
  message: string
  due_at: string | null
  created_at: string
  read_at: string | null
}

export interface NotificationListDto {
  items: NotificationDto[]
  unread_count: number
}

export interface ReportDto {
  id: string
  report_type: ReportType
  title: string
  period_start: string
  period_end: string
  project_id: string | null
  project_name: string | null
  content_md: string
  facts: ReportFacts
  ai_used: boolean
  created_at: string
  updated_at: string
}

export interface ReportDraftDto {
  report_type: ReportType
  title: string
  period_start: string
  period_end: string
  project_id: string | null
  project_name: string | null
  content_md: string
  facts: ReportFacts
  ai_used: boolean
}

export interface ReportSummaryDto {
  id: string
  report_type: ReportType
  title: string
  period_start: string
  period_end: string
  project_id: string | null
  project_name: string | null
  ai_used: boolean
  created_at: string
}

export interface PrioritySuggestionDto {
  task_id: string
  title: string
  current_priority: TaskPriority
  suggested_priority: TaskPriority
  score: number
  reasons: string[]
  due_at: string | null
  project_id: string | null
  project_name: string | null
  estimated_minutes: number | null
}

export interface DashboardDto {
  date: string
  timezone: string
  counts: {
    total: number
    pending: number
    completed: number
    overdue: number
    due_today: number
    due_soon: number
  }
  today_tasks: TaskDto[]
  due_soon_tasks: TaskDto[]
  overdue_tasks: TaskDto[]
  projects: ProjectDto[]
  today_plan: PlanDto | null
  recent_activities: ActivityDto[]
  unread_notifications: number
}

export interface BreakdownSubtaskDto {
  title: string
  description: string | null
  priority: TaskPriority
  estimated_minutes: number | null
  due_at: string | null
}

export interface BreakdownTaskDto extends BreakdownSubtaskDto {
  subtasks: BreakdownSubtaskDto[]
}

export interface BreakdownDto {
  goal: string
  project_id: string | null
  project_name: string | null
  tasks: BreakdownTaskDto[]
}

export interface PlanDraftDto {
  plan_date: string
  available_minutes: number
  items: Array<{
    task_id: string
    task_title?: string | null
    start_at: string
    end_at: string
    note: string | null
  }>
}

export interface TaskDraftDto {
  title: string
  description: string | null
  due_at: string | null
  priority?: TaskPriority
  estimated_minutes?: number | null
  project_id?: string | null
}

export function mapTask(dto: TaskDto): Task {
  return {
    id: dto.id,
    title: dto.title,
    description: dto.description,
    status: dto.status,
    dueAt: dto.due_at,
    projectId: dto.project_id,
    parentId: dto.parent_id,
    priority: dto.priority,
    estimatedMinutes: dto.estimated_minutes,
    position: dto.position,
    completedAt: dto.completed_at,
    createdAt: dto.created_at,
    updatedAt: dto.updated_at,
    subtaskCount: dto.subtask_count,
    completedSubtaskCount: dto.completed_subtask_count,
  }
}

function mapStats(dto: ProjectStatsDto): ProjectStats {
  return {
    totalTasks: dto.total_tasks,
    completedTasks: dto.completed_tasks,
    pendingTasks: dto.pending_tasks,
    overdueTasks: dto.overdue_tasks,
    completionRate: dto.completion_rate,
  }
}

export function mapProject(dto: ProjectDto): Project {
  return {
    id: dto.id,
    name: dto.name,
    description: dto.description,
    status: dto.status,
    startDate: dto.start_date,
    dueDate: dto.due_date,
    createdAt: dto.created_at,
    updatedAt: dto.updated_at,
    stats: mapStats(dto.stats),
  }
}

export function mapActivity(dto: ActivityDto): Activity {
  return {
    id: dto.id,
    taskId: dto.task_id,
    taskTitle: dto.task_title,
    projectId: dto.project_id,
    projectName: dto.project_name,
    action: dto.action,
    field: dto.field,
    oldValue: dto.old_value,
    newValue: dto.new_value,
    summary: dto.summary,
    createdAt: dto.created_at,
  }
}

function mapPlanItem(dto: PlanItemDto): PlanItem {
  return {
    id: dto.id,
    taskId: dto.task_id,
    taskTitle: dto.task_title,
    taskStatus: dto.task_status,
    priority: dto.priority,
    estimatedMinutes: dto.estimated_minutes,
    startAt: dto.start_at,
    endAt: dto.end_at,
    position: dto.position,
    note: dto.note,
  }
}

export function mapPlan(dto: PlanDto): Plan {
  return {
    id: dto.id,
    planDate: dto.plan_date,
    timezone: dto.timezone,
    availableMinutes: dto.available_minutes,
    plannedMinutes: dto.planned_minutes,
    items: dto.items.map(mapPlanItem),
    createdAt: dto.created_at,
    updatedAt: dto.updated_at,
  }
}

export function mapNotification(dto: NotificationDto): AppNotification {
  return {
    id: dto.id,
    type: dto.type,
    taskId: dto.task_id,
    taskTitle: dto.task_title,
    message: dto.message,
    dueAt: dto.due_at,
    createdAt: dto.created_at,
    readAt: dto.read_at,
  }
}

export function mapNotificationList(dto: NotificationListDto): NotificationList {
  return {
    items: dto.items.map(mapNotification),
    unreadCount: dto.unread_count,
  }
}

function mapReportFields(dto: ReportDraftDto): ReportDraft {
  return {
    reportType: dto.report_type,
    title: dto.title,
    periodStart: dto.period_start,
    periodEnd: dto.period_end,
    projectId: dto.project_id,
    projectName: dto.project_name,
    contentMd: dto.content_md,
    facts: dto.facts,
    aiUsed: dto.ai_used,
  }
}

export function mapReportDraft(dto: ReportDraftDto): ReportDraft {
  return mapReportFields(dto)
}

export function mapReport(dto: ReportDto): Report {
  return {
    ...mapReportFields(dto),
    id: dto.id,
    createdAt: dto.created_at,
    updatedAt: dto.updated_at,
  }
}

export function mapReportSummary(dto: ReportSummaryDto): ReportSummary {
  return {
    id: dto.id,
    reportType: dto.report_type,
    title: dto.title,
    periodStart: dto.period_start,
    periodEnd: dto.period_end,
    projectId: dto.project_id,
    projectName: dto.project_name,
    aiUsed: dto.ai_used,
    createdAt: dto.created_at,
  }
}

function mapDashboardCounts(dto: DashboardDto['counts']): DashboardCounts {
  return {
    total: dto.total,
    pending: dto.pending,
    completed: dto.completed,
    overdue: dto.overdue,
    dueToday: dto.due_today,
    dueSoon: dto.due_soon,
  }
}

export function mapDashboard(dto: DashboardDto): Dashboard {
  return {
    date: dto.date,
    timezone: dto.timezone,
    counts: mapDashboardCounts(dto.counts),
    todayTasks: dto.today_tasks.map(mapTask),
    dueSoonTasks: dto.due_soon_tasks.map(mapTask),
    overdueTasks: dto.overdue_tasks.map(mapTask),
    projects: dto.projects.map(mapProject),
    todayPlan: dto.today_plan ? mapPlan(dto.today_plan) : null,
    recentActivities: dto.recent_activities.map(mapActivity),
    unreadNotifications: dto.unread_notifications,
  }
}

export function mapPrioritySuggestion(dto: PrioritySuggestionDto): PrioritySuggestion {
  return {
    taskId: dto.task_id,
    title: dto.title,
    currentPriority: dto.current_priority,
    suggestedPriority: dto.suggested_priority,
    score: dto.score,
    reasons: dto.reasons,
    dueAt: dto.due_at,
    projectId: dto.project_id,
    projectName: dto.project_name,
    estimatedMinutes: dto.estimated_minutes,
  }
}

function mapBreakdownSubtask(dto: BreakdownSubtaskDto): BreakdownSubtaskDraft {
  return {
    title: dto.title,
    description: dto.description,
    priority: dto.priority,
    estimatedMinutes: dto.estimated_minutes,
    dueAt: dto.due_at,
  }
}

export function mapBreakdown(dto: BreakdownDto): BreakdownDraft {
  return {
    goal: dto.goal,
    projectId: dto.project_id,
    projectName: dto.project_name,
    tasks: dto.tasks.map((task) => ({
      ...mapBreakdownSubtask(task),
      subtasks: task.subtasks.map(mapBreakdownSubtask),
    })),
  }
}

export function mapPlanDraft(dto: PlanDraftDto): PlanDraft {
  return {
    planDate: dto.plan_date,
    availableMinutes: dto.available_minutes,
    items: dto.items.map((item) => ({
      taskId: item.task_id,
      taskTitle: item.task_title ?? null,
      startAt: item.start_at,
      endAt: item.end_at,
      note: item.note,
    })),
  }
}

export function mapTaskDraft(dto: TaskDraftDto): TaskDraft {
  return {
    title: dto.title,
    description: dto.description,
    dueAt: dto.due_at,
    priority: dto.priority ?? 'medium',
    estimatedMinutes: dto.estimated_minutes ?? null,
    projectId: dto.project_id ?? null,
  }
}
