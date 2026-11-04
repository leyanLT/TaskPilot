export type TaskStatus = 'pending' | 'completed'
export type TaskPriority = 'high' | 'medium' | 'low'
export type ProjectStatus = 'planning' | 'active' | 'completed' | 'archived'
export type NotificationType = 'today_todo' | 'due_soon' | 'overdue'
export type ReportType = 'daily' | 'weekly' | 'project'
export type ActivityAction =
  | 'task_created'
  | 'task_updated'
  | 'task_completed'
  | 'task_reopened'
  | 'task_deleted'
  | 'task_project_changed'
  | 'subtask_created'
  | 'project_created'
  | 'project_updated'
  | 'project_status_changed'

export type ActionType =
  | 'create_task'
  | 'create_tasks'
  | 'complete_task'
  | 'update_task'
  | 'delete_task'
  | 'batch_reschedule'
  | 'create_task_breakdown'
  | 'save_daily_plan'
  | 'save_report'
  | 'apply_replan'
  | 'create_project'
export type ActionStatus = 'pending' | 'processing' | 'confirmed' | 'cancelled' | 'expired'

export interface Task {
  id: string
  title: string
  description: string | null
  status: TaskStatus
  dueAt: string | null
  projectId: string | null
  parentId: string | null
  priority: TaskPriority
  estimatedMinutes: number | null
  position: number
  completedAt: string | null
  createdAt: string
  updatedAt: string
  subtaskCount: number
  completedSubtaskCount: number
}

export interface TaskInput {
  title: string
  description?: string | null
  dueAt?: string | null
  projectId?: string | null
  priority?: TaskPriority
  estimatedMinutes?: number | null
}

export interface SubtaskInput {
  title: string
  description?: string | null
  dueAt?: string | null
  priority?: TaskPriority
  estimatedMinutes?: number | null
}

export interface TaskPatch {
  title?: string
  description?: string | null
  dueAt?: string | null
  status?: TaskStatus
  projectId?: string | null
  priority?: TaskPriority
  estimatedMinutes?: number | null
}

export interface TaskDetail extends Task {
  subtasks: Task[]
  parent: Task | null
}

export interface ProjectStats {
  totalTasks: number
  completedTasks: number
  pendingTasks: number
  overdueTasks: number
  completionRate: number
}

export interface Project {
  id: string
  name: string
  description: string | null
  status: ProjectStatus
  startDate: string | null
  dueDate: string | null
  createdAt: string
  updatedAt: string
  stats: ProjectStats
}

export interface ProjectInput {
  name: string
  description?: string | null
  status?: ProjectStatus
  startDate?: string | null
  dueDate?: string | null
}

export interface Activity {
  id: string
  taskId: string | null
  taskTitle: string | null
  projectId: string | null
  projectName: string | null
  action: ActivityAction
  field: string | null
  oldValue: string | null
  newValue: string | null
  summary: string
  createdAt: string
}

export interface ProjectDetail {
  project: Project
  tasks: Task[]
  recentActivities: Activity[]
}

export interface PlanItem {
  id: string
  taskId: string
  taskTitle: string
  taskStatus: TaskStatus
  priority: TaskPriority
  estimatedMinutes: number | null
  startAt: string
  endAt: string
  position: number
  note: string | null
}

export interface Plan {
  id: string
  planDate: string
  timezone: string
  availableMinutes: number
  plannedMinutes: number
  items: PlanItem[]
  createdAt: string
  updatedAt: string
}

export interface PlanItemInput {
  taskId: string
  startAt: string
  endAt: string
  note?: string | null
}

export interface PlanSuggestionItem {
  taskId: string
  title: string
  priority: TaskPriority
  estimatedMinutes: number
  isEstimate: boolean
  startAt: string
  endAt: string
  reasons: string[]
}

export interface PlanSuggestion {
  planDate: string
  availableMinutes: number
  blocks: PlanSuggestionItem[]
}

export interface AppNotification {
  id: string
  type: NotificationType
  taskId: string | null
  taskTitle: string | null
  message: string
  dueAt: string | null
  createdAt: string
  readAt: string | null
}

export interface NotificationList {
  items: AppNotification[]
  unreadCount: number
}

export interface ReportSummary {
  id: string
  reportType: ReportType
  title: string
  periodStart: string
  periodEnd: string
  projectId: string | null
  projectName: string | null
  aiUsed: boolean
  createdAt: string
}

export interface ReportFacts {
  [key: string]: unknown
}

export interface ReportDraft {
  reportType: ReportType
  title: string
  periodStart: string
  periodEnd: string
  projectId: string | null
  projectName: string | null
  contentMd: string
  facts: ReportFacts
  aiUsed: boolean
}

export interface Report extends ReportDraft {
  id: string
  createdAt: string
  updatedAt: string
}

export interface ReportGenerateInput {
  reportType: ReportType
  periodStart?: string | null
  periodEnd?: string | null
  projectId?: string | null
}

export interface PrioritySuggestion {
  taskId: string
  title: string
  currentPriority: TaskPriority
  suggestedPriority: TaskPriority
  score: number
  reasons: string[]
  dueAt: string | null
  projectId: string | null
  projectName: string | null
  estimatedMinutes: number | null
}

export interface DashboardCounts {
  total: number
  pending: number
  completed: number
  overdue: number
  dueToday: number
  dueSoon: number
}

export interface Dashboard {
  date: string
  timezone: string
  counts: DashboardCounts
  todayTasks: Task[]
  dueSoonTasks: Task[]
  overdueTasks: Task[]
  projects: Project[]
  todayPlan: Plan | null
  recentActivities: Activity[]
  unreadNotifications: number
}

export interface BreakdownSubtaskDraft {
  title: string
  description: string | null
  priority: TaskPriority
  estimatedMinutes: number | null
  dueAt: string | null
}

export interface BreakdownTaskDraft extends BreakdownSubtaskDraft {
  subtasks: BreakdownSubtaskDraft[]
}

export interface BreakdownDraft {
  goal: string
  projectId: string | null
  projectName: string | null
  tasks: BreakdownTaskDraft[]
}

export interface PlanDraftItem {
  taskId: string
  taskTitle: string | null
  startAt: string
  endAt: string
  note: string | null
}

export interface PlanDraft {
  planDate: string
  availableMinutes: number
  items: PlanDraftItem[]
}

export interface TaskDraft {
  title: string
  description: string | null
  dueAt: string | null
  priority: TaskPriority
  estimatedMinutes: number | null
  projectId: string | null
}

export interface TaskChanges {
  title: string | null
  description: string | null
  dueAt: string | null
  priority: TaskPriority | null
  estimatedMinutes: number | null
  projectId: string | null
  projectName: string | null
  changedFields: string[]
}

export interface PendingAction {
  id: string
  actionType: ActionType
  status: ActionStatus
  summary: string
  proposedTask: TaskDraft | null
  proposedTasks: TaskDraft[]
  targetTask: Task | null
  targetTasks: Task[]
  changes: TaskChanges | null
  proposedBreakdown: BreakdownDraft | null
  proposedPlan: PlanDraft | null
  proposedReport: ReportDraft | null
  proposedReplan: Record<string, unknown> | null
  proposedProject: Record<string, unknown> | null
  createdAt: string
  expiresAt: string
}

export interface TaskCandidate {
  id: string
  title: string
  dueAt: string | null
  status: TaskStatus
}

export type ChatRole = 'user' | 'assistant'

export interface AssistantMessage {
  id: string
  role: ChatRole
  content: string
  action: PendingAction | null
  candidates: TaskCandidate[]
  promptVersion: string | null
  createdAt: string
}

export interface AssistantTurn {
  userMessage: AssistantMessage
  assistantMessage: AssistantMessage
}

export interface AssistantChatMessage extends AssistantMessage {
  isError?: boolean
  streaming?: boolean
  streamStatus?: string
}

export type AssistantStreamPhase =
  | 'thinking'
  | 'using_tools'
  | 'preparing_action'
  | 'composing'

export type AssistantStreamEvent =
  | { type: 'started'; userMessage: AssistantMessage; promptVersion: string | null }
  | { type: 'status'; phase: AssistantStreamPhase }
  | { type: 'token'; delta: string }
  | { type: 'done'; assistantMessage: AssistantMessage }
  | { type: 'error'; code: string; message: string }

export interface ConfirmResult {
  actionId: string
  status: ActionStatus
  message: string
  task: Task | null
  affectedTasks: Task[]
  reportId: string | null
  planDate: string | null
}

export type TaskFilter = 'all' | TaskStatus
export type TaskSort = 'created_desc' | 'created_asc' | 'due_asc' | 'due_desc' | 'priority'

export type AppRoute =
  | { name: 'dashboard' }
  | { name: 'tasks' }
  | { name: 'projects' }
  | { name: 'project'; id: string }
  | { name: 'assistant' }
  | { name: 'today' }
  | { name: 'calendar' }
  | { name: 'focus' }
  | { name: 'settings' }
  | { name: 'reports' }
  | { name: 'report'; id: string }
  | { name: 'notifications' }

export const PRIORITY_LABELS: Record<TaskPriority, string> = {
  high: '高',
  medium: '中',
  low: '弱',
}

export const PROJECT_STATUS_LABELS: Record<ProjectStatus, string> = {
  planning: '规划中',
  active: '进行中',
  completed: '已完成',
  archived: '已归档',
}

export const REPORT_TYPE_LABELS: Record<ReportType, string> = {
  daily: '日报',
  weekly: '周报',
  project: '项目报告',
}

export const NOTIFICATION_TYPE_LABELS: Record<NotificationType, string> = {
  today_todo: '今日待办',
  due_soon: '即将截止',
  overdue: '已逾期',
}
