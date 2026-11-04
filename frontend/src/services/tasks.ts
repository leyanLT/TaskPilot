import type {
  SubtaskInput,
  Task,
  TaskDetail,
  TaskInput,
  TaskPatch,
  TaskPriority,
  TaskStatus,
} from '../types'
import { request } from './http'
import { mapTask, type TaskDto } from './mappers'

export interface TaskListQuery {
  status?: TaskStatus
  sortBy?: 'created_at' | 'due_at' | 'priority'
  order?: 'asc' | 'desc'
  projectId?: string
  priority?: TaskPriority
  includeSubtasks?: boolean
}

interface TaskDetailDto extends TaskDto {
  subtasks: TaskDto[]
  parent: TaskDto | null
}

function queryString(params: Record<string, string | boolean | undefined>): string {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === '') {
      return
    }
    search.set(key, String(value))
  })
  const encoded = search.toString()
  return encoded ? `?${encoded}` : ''
}

export const taskApi = {
  async list(query: TaskListQuery = {}): Promise<Task[]> {
    const suffix = queryString({
      status: query.status,
      sort_by: query.sortBy,
      order: query.order,
      project_id: query.projectId,
      priority: query.priority,
      include_subtasks: query.includeSubtasks,
    })
    const data = await request<TaskDto[]>(`/tasks${suffix}`)
    return data.map(mapTask)
  },

  async detail(taskId: string): Promise<TaskDetail> {
    const dto = await request<TaskDetailDto>(
      `/tasks/${encodeURIComponent(taskId)}`,
    )
    return {
      ...mapTask(dto),
      subtasks: dto.subtasks.map(mapTask),
      parent: dto.parent ? mapTask(dto.parent) : null,
    }
  },

  async create(input: TaskInput): Promise<Task> {
    const dto = await request<TaskDto>('/tasks', {
      method: 'POST',
      body: JSON.stringify({
        title: input.title,
        description: input.description ?? null,
        due_at: input.dueAt ?? null,
        project_id: input.projectId ?? null,
        priority: input.priority ?? 'medium',
        estimated_minutes: input.estimatedMinutes ?? null,
      }),
    })
    return mapTask(dto)
  },

  async update(taskId: string, patch: TaskPatch): Promise<Task> {
    const body: Record<string, unknown> = {}
    if (patch.title !== undefined) body.title = patch.title
    if (patch.description !== undefined) body.description = patch.description
    if (patch.dueAt !== undefined) body.due_at = patch.dueAt
    if (patch.status !== undefined) body.status = patch.status
    if (patch.projectId !== undefined) body.project_id = patch.projectId
    if (patch.priority !== undefined) body.priority = patch.priority
    if (patch.estimatedMinutes !== undefined) {
      body.estimated_minutes = patch.estimatedMinutes
    }
    const dto = await request<TaskDto>(`/tasks/${encodeURIComponent(taskId)}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    })
    return mapTask(dto)
  },

  async remove(taskId: string, confirmSubtasks = false): Promise<void> {
    const suffix = confirmSubtasks ? '?confirm_subtasks=true' : ''
    await request<void>(`/tasks/${encodeURIComponent(taskId)}${suffix}`, {
      method: 'DELETE',
    })
  },

  async subtasks(taskId: string): Promise<Task[]> {
    const data = await request<TaskDto[]>(
      `/tasks/${encodeURIComponent(taskId)}/subtasks`,
    )
    return data.map(mapTask)
  },

  async addSubtask(parentId: string, input: SubtaskInput): Promise<Task> {
    const dto = await request<TaskDto>(
      `/tasks/${encodeURIComponent(parentId)}/subtasks`,
      {
        method: 'POST',
        body: JSON.stringify({
          title: input.title,
          description: input.description ?? null,
          due_at: input.dueAt ?? null,
          priority: input.priority ?? 'medium',
          estimated_minutes: input.estimatedMinutes ?? null,
        }),
      },
    )
    return mapTask(dto)
  },

  async reorderSubtasks(parentId: string, subtaskIds: string[]): Promise<Task[]> {
    const data = await request<TaskDto[]>(
      `/tasks/${encodeURIComponent(parentId)}/subtasks/order`,
      {
        method: 'PUT',
        body: JSON.stringify({ subtask_ids: subtaskIds }),
      },
    )
    return data.map(mapTask)
  },
}
