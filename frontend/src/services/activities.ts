import type { Activity } from '../types'
import { request } from './http'
import { mapActivity, type ActivityDto } from './mappers'

export interface ActivityQuery {
  projectId?: string
  taskId?: string
  limit?: number
}

function queryString(params: Record<string, string | number | undefined>): string {
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

export const activityApi = {
  async list(query: ActivityQuery = {}): Promise<Activity[]> {
    const suffix = queryString({
      project_id: query.projectId,
      task_id: query.taskId,
      limit: query.limit,
    })
    const data = await request<ActivityDto[]>(`/activities${suffix}`)
    return data.map(mapActivity)
  },
}
