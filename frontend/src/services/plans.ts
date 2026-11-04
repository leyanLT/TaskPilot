import type { Plan, PlanItemInput, PlanSuggestion, TaskPriority } from '../types'
import { ApiError, request } from './http'
import { mapPlan, type PlanDto } from './mappers'

interface SuggestionBlockDto {
  task_id: string
  title: string
  priority: TaskPriority
  estimated_minutes: number
  is_estimate: boolean
  start_at: string
  end_at: string
  reasons: string[]
}

interface SuggestionDto {
  plan_date: string
  available_minutes: number
  blocks: SuggestionBlockDto[]
}

export interface PlanInput {
  availableMinutes: number
  items: PlanItemInput[]
}

export const planApi = {
  async get(planDate: string): Promise<Plan | null> {
    try {
      const dto = await request<PlanDto>(`/plans/${encodeURIComponent(planDate)}`)
      return mapPlan(dto)
    } catch (error) {
      if (error instanceof ApiError && error.code === 'PLAN_NOT_FOUND') {
        return null
      }
      throw error
    }
  },

  async save(planDate: string, input: PlanInput): Promise<Plan> {
    const dto = await request<PlanDto>(`/plans/${encodeURIComponent(planDate)}`, {
      method: 'PUT',
      body: JSON.stringify({
        available_minutes: input.availableMinutes,
        items: input.items.map((item) => ({
          task_id: item.taskId,
          start_at: item.startAt,
          end_at: item.endAt,
          note: item.note ?? null,
        })),
      }),
    })
    return mapPlan(dto)
  },

  async remove(planDate: string): Promise<void> {
    await request<void>(`/plans/${encodeURIComponent(planDate)}`, {
      method: 'DELETE',
    })
  },

  async suggestion(
    planDate: string,
    availableMinutes: number,
  ): Promise<PlanSuggestion> {
    const dto = await request<SuggestionDto>(
      `/plans/${encodeURIComponent(planDate)}/suggestion?available_minutes=${availableMinutes}`,
    )
    return {
      planDate: dto.plan_date,
      availableMinutes: dto.available_minutes,
      blocks: dto.blocks.map((block) => ({
        taskId: block.task_id,
        title: block.title,
        priority: block.priority,
        estimatedMinutes: block.estimated_minutes,
        isEstimate: block.is_estimate,
        startAt: block.start_at,
        endAt: block.end_at,
        reasons: block.reasons,
      })),
    }
  },
}
