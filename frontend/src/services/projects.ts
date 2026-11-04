import type { Project, ProjectDetail, ProjectInput, ProjectStatus } from '../types'
import { request } from './http'
import {
  mapActivity,
  mapProject,
  mapTask,
  type ActivityDto,
  type ProjectDto,
  type TaskDto,
} from './mappers'

interface ProjectDetailDto {
  project: ProjectDto
  tasks: TaskDto[]
  recent_activities: ActivityDto[]
}

export interface ProjectListQuery {
  status?: ProjectStatus
  includeArchived?: boolean
  search?: string
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

function body(input: ProjectInput): Record<string, unknown> {
  const payload: Record<string, unknown> = { name: input.name }
  if (input.description !== undefined) payload.description = input.description
  if (input.status !== undefined) payload.status = input.status
  if (input.startDate !== undefined) payload.start_date = input.startDate
  if (input.dueDate !== undefined) payload.due_date = input.dueDate
  return payload
}

export const projectApi = {
  async list(query: ProjectListQuery = {}): Promise<Project[]> {
    const suffix = queryString({
      status: query.status,
      include_archived: query.includeArchived,
      search: query.search,
    })
    const data = await request<ProjectDto[]>(`/projects${suffix}`)
    return data.map(mapProject)
  },

  async get(projectId: string): Promise<ProjectDetail> {
    const dto = await request<ProjectDetailDto>(
      `/projects/${encodeURIComponent(projectId)}`,
    )
    return {
      project: mapProject(dto.project),
      tasks: dto.tasks.map(mapTask),
      recentActivities: dto.recent_activities.map(mapActivity),
    }
  },

  async create(input: ProjectInput): Promise<Project> {
    const dto = await request<ProjectDto>('/projects', {
      method: 'POST',
      body: JSON.stringify(body(input)),
    })
    return mapProject(dto)
  },

  async update(projectId: string, input: Partial<ProjectInput>): Promise<Project> {
    const payload: Record<string, unknown> = {}
    if (input.name !== undefined) payload.name = input.name
    if (input.description !== undefined) payload.description = input.description
    if (input.status !== undefined) payload.status = input.status
    if (input.startDate !== undefined) payload.start_date = input.startDate
    if (input.dueDate !== undefined) payload.due_date = input.dueDate
    const dto = await request<ProjectDto>(
      `/projects/${encodeURIComponent(projectId)}`,
      { method: 'PATCH', body: JSON.stringify(payload) },
    )
    return mapProject(dto)
  },

  async archive(projectId: string): Promise<Project> {
    const dto = await request<ProjectDto>(
      `/projects/${encodeURIComponent(projectId)}/archive`,
      { method: 'POST' },
    )
    return mapProject(dto)
  },

  async restore(projectId: string): Promise<Project> {
    const dto = await request<ProjectDto>(
      `/projects/${encodeURIComponent(projectId)}/restore`,
      { method: 'POST' },
    )
    return mapProject(dto)
  },
}
