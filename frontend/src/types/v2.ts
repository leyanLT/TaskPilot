import type { ProjectStats, TaskPriority, TaskStatus } from './index'

export type RecurrenceFrequency = 'daily' | 'weekly' | 'monthly' | 'custom_weekly'

export interface DependencyLink {
  id: string
  taskId: string
  dependsOnTaskId: string
  dependsOnTitle: string
  dependsOnStatus: TaskStatus
  createdAt: string
}

export interface TaskDependencies {
  taskId: string
  isBlocked: boolean
  dependsOn: DependencyLink[]
  blocks: DependencyLink[]
}

export interface RecurrenceRule {
  id: string
  title: string
  description: string | null
  projectId: string | null
  priority: TaskPriority
  estimatedMinutes: number | null
  frequency: RecurrenceFrequency
  interval: number
  weekdays: number[] | null
  startDate: string
  endDate: string | null
  dueTime: string | null
  timezone: string
  paused: boolean
  nextOccurrence: string | null
  generatedCount: number
  completedCount: number
  pendingCount: number
  createdAt: string
  updatedAt: string
}

export interface RecurrenceInput {
  title: string
  description?: string | null
  projectId?: string | null
  priority?: TaskPriority
  estimatedMinutes?: number | null
  frequency: RecurrenceFrequency
  interval?: number
  weekdays?: number[] | null
  startDate: string
  endDate?: string | null
  dueTime?: string | null
}

export type FocusStatus = 'running' | 'paused' | 'completed' | 'cancelled'

export interface FocusSession {
  id: string
  taskId: string
  taskTitle: string
  taskEstimatedMinutes: number | null
  status: FocusStatus
  mode: 'free' | 'pomodoro'
  plannedMinutes: number | null
  elapsedSeconds: number
  accumulatedSeconds: number
  targetSeconds: number | null
  remainingSeconds: number | null
  startedAt: string
  lastResumedAt: string | null
  endedAt: string | null
  syncedAt: string
}

export interface FocusDay {
  date: string
  seconds: number
}

export interface FocusTaskTotal {
  taskId: string
  title: string
  seconds: number
}

export interface FocusStats {
  today: string
  todaySeconds: number
  weekSeconds: number
  sessionCount: number
  byDay: FocusDay[]
  byTask: FocusTaskTotal[]
}

export interface TimeBlock {
  id: string
  planId: string
  planDate: string
  taskId: string
  taskTitle: string
  taskStatus: TaskStatus
  startAt: string
  endAt: string
  note: string | null
  position: number
}

export interface CalendarTask {
  id: string
  title: string
  status: TaskStatus
  priority: TaskPriority
  dueAt: string | null
  projectId: string | null
  isBlocked: boolean
  recurrenceRuleId: string | null
}

export interface CalendarDay {
  date: string
  availableMinutes: number
  plannedMinutes: number
  blocks: TimeBlock[]
  dueTasks: CalendarTask[]
}

export interface CalendarRange {
  start: string
  end: string
  days: CalendarDay[]
  totalPlannedMinutes: number
}

export type InsightSeverity = 'high' | 'medium' | 'low'

export interface Insight {
  key: string
  code: string
  severity: InsightSeverity
  title: string
  reason: string
  suggestion: string
  taskIds: string[]
  taskTitles: string[]
  projectId: string | null
  metric: Record<string, unknown>
}

export interface InsightList {
  generatedAt: string
  items: Insight[]
  dismissedCount: number
}

export interface ReplanBlock {
  taskId: string
  title: string
  priority: TaskPriority
  estimatedMinutes: number
  startAt: string
  endAt: string
  reasons: string[]
}

export interface ReplanChange {
  kind: 'added' | 'moved' | 'removed' | 'kept'
  taskId: string
  title: string
  beforeStart: string | null
  afterStart: string | null
}

export interface ReplanDraft {
  planDate: string
  availableMinutes: number
  before: ReplanBlock[]
  after: ReplanBlock[]
  changes: ReplanChange[]
  blockedTasks: Array<{ taskId: string; title: string; blockedBy: string[] }>
  unscheduled: Array<{ taskId: string; title: string; blockedBy: string[] }>
  explanation: string[]
  planToken: string
}

export interface Preferences {
  timezone: string
  dailyAvailableMinutes: number
  workdays: number[]
  defaultFocusMinutes: number
  reminderPrefs: Record<string, unknown>
  updatedAt: string
}

export interface ProjectRisk {
  id: string
  name: string
  status: string
  dueDate: string | null
  stats: ProjectStats
}
