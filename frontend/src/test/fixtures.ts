import type {
  AssistantMessage,
  AssistantTurn,
  PendingAction,
  Project,
  Task,
  TaskCandidate,
} from '../types'

export function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: 'task-1',
    title: '测试任务',
    description: '任务描述',
    status: 'pending',
    dueAt: '2999-01-01T10:00:00+00:00',
    projectId: null,
    parentId: null,
    priority: 'medium',
    estimatedMinutes: null,
    position: 0,
    completedAt: null,
    createdAt: '2026-01-01T08:00:00+00:00',
    updatedAt: '2026-01-01T08:00:00+00:00',
    subtaskCount: 0,
    completedSubtaskCount: 0,
    ...overrides,
  }
}

export function makeProject(overrides: Partial<Project> = {}): Project {
  return {
    id: 'project-1',
    name: '测试项目',
    description: '项目描述',
    status: 'active',
    startDate: '2026-01-01',
    dueDate: '2026-12-31',
    createdAt: '2026-01-01T08:00:00+00:00',
    updatedAt: '2026-01-01T08:00:00+00:00',
    stats: {
      totalTasks: 0,
      completedTasks: 0,
      pendingTasks: 0,
      overdueTasks: 0,
      completionRate: 0,
    },
    ...overrides,
  }
}

export function makeAction(overrides: Partial<PendingAction> = {}): PendingAction {
  return {
    id: 'action-1',
    actionType: 'create_task',
    status: 'pending',
    summary: '创建任务「新任务」',
    proposedTask: {
      title: '新任务',
      description: '一个新任务',
      dueAt: '2999-01-01T10:00:00+00:00',
      priority: 'medium',
      estimatedMinutes: null,
      projectId: null,
    },
    proposedTasks: [],
    targetTask: null,
    targetTasks: [],
    changes: null,
    proposedBreakdown: null,
    proposedPlan: null,
    proposedReport: null,
    proposedReplan: null,
    proposedProject: null,
    createdAt: '2026-01-01T08:00:00+00:00',
    expiresAt: '2999-01-01T09:00:00+00:00',
    ...overrides,
  }
}

export function makeCandidate(overrides: Partial<TaskCandidate> = {}): TaskCandidate {
  return {
    id: 'candidate-1',
    title: '候选任务',
    dueAt: '2999-01-01T10:00:00+00:00',
    status: 'pending',
    ...overrides,
  }
}

export function makeAssistantMessage(
  overrides: Partial<AssistantMessage> = {},
): AssistantMessage {
  return {
    id: 'assistant-message-1',
    role: 'assistant',
    content: '助手回复',
    action: null,
    candidates: [],
    promptVersion: '2026-11-v5',
    createdAt: '2026-01-01T08:00:00+00:00',
    ...overrides,
  }
}

export function makeAssistantTurn(
  overrides: Partial<AssistantTurn> = {},
): AssistantTurn {
  return {
    userMessage: makeAssistantMessage({
      id: 'user-message-1',
      role: 'user',
      content: '用户消息',
      promptVersion: null,
    }),
    assistantMessage: makeAssistantMessage(),
    ...overrides,
  }
}
