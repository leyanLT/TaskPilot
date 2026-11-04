import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TodayPage } from '../TodayPage'
import { planApi } from '../../services/plans'
import { taskApi } from '../../services/tasks'
import { renderWithApp } from '../../test/render'
import { makeTask } from '../../test/fixtures'

vi.mock('../../services/plans', () => ({
  planApi: {
    get: vi.fn(),
    save: vi.fn(),
    remove: vi.fn(),
    suggestion: vi.fn(),
  },
}))

vi.mock('../../services/tasks', () => ({
  taskApi: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    detail: vi.fn(),
    subtasks: vi.fn(),
    addSubtask: vi.fn(),
    reorderSubtasks: vi.fn(),
  },
}))

const mockedPlans = vi.mocked(planApi)
const mockedTasks = vi.mocked(taskApi)

function makePlan() {
  return {
    id: 'plan-1',
    planDate: '2026-11-03',
    timezone: 'Asia/Shanghai',
    availableMinutes: 300,
    plannedMinutes: 60,
    items: [
      {
        id: 'item-1',
        taskId: 'task-1',
        taskTitle: '写方案',
        taskStatus: 'pending' as const,
        priority: 'high' as const,
        estimatedMinutes: 60,
        startAt: '2026-11-03T01:00:00+00:00',
        endAt: '2026-11-03T02:00:00+00:00',
        position: 0,
        note: null,
      },
    ],
    createdAt: '2026-11-03T00:00:00+00:00',
    updatedAt: '2026-11-03T00:00:00+00:00',
  }
}

describe('TodayPage', () => {
  beforeEach(() => {
    mockedPlans.get.mockReset()
    mockedPlans.save.mockReset()
    mockedPlans.remove.mockReset()
    mockedPlans.suggestion.mockReset()
    mockedTasks.list.mockReset()
    mockedTasks.update.mockReset()
    mockedTasks.list.mockResolvedValue([
      makeTask({ id: 'task-1', title: '写方案' }),
      makeTask({ id: 'task-2', title: '读文档' }),
    ])
  })

  it('shows an empty plan and can produce a suggestion', async () => {
    mockedPlans.get.mockResolvedValue(null)
    mockedPlans.suggestion.mockResolvedValue({
      planDate: '2026-11-03',
      availableMinutes: 300,
      blocks: [
        {
          taskId: 'task-1',
          title: '写方案',
          priority: 'high',
          estimatedMinutes: 60,
          isEstimate: false,
          startAt: '2026-11-03T01:00:00+00:00',
          endAt: '2026-11-03T02:00:00+00:00',
          reasons: ['任务已逾期'],
        },
      ],
    })
    const user = userEvent.setup()
    renderWithApp(<TodayPage dataVersion={0} onDataChanged={vi.fn()} />)

    await screen.findByText('还没有计划')
    await user.click(screen.getByRole('button', { name: '生成时间块建议' }))

    expect(await screen.findByRole('button', { name: '采用建议' })).toBeInTheDocument()
    expect(mockedPlans.suggestion).toHaveBeenCalledWith(expect.any(String), 300)
  })

  it('adopts a suggestion by saving real time blocks', async () => {
    mockedPlans.get.mockResolvedValue(null)
    mockedPlans.suggestion.mockResolvedValue({
      planDate: '2026-11-03',
      availableMinutes: 300,
      blocks: [
        {
          taskId: 'task-2',
          title: '读文档',
          priority: 'medium',
          estimatedMinutes: 30,
          isEstimate: true,
          startAt: '2026-11-03T01:00:00+00:00',
          endAt: '2026-11-03T01:30:00+00:00',
          reasons: ['未填写预计耗时，按 30 分钟估算'],
        },
      ],
    })
    mockedPlans.save.mockResolvedValue(makePlan())
    const user = userEvent.setup()
    renderWithApp(<TodayPage dataVersion={0} onDataChanged={vi.fn()} />)

    await screen.findByText('还没有计划')
    await user.click(screen.getByRole('button', { name: '生成时间块建议' }))
    await user.click(await screen.findByRole('button', { name: '采用建议' }))

    await waitFor(() => {
      expect(mockedPlans.save).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          availableMinutes: 300,
          items: [
            {
              taskId: 'task-2',
              startAt: '2026-11-03T01:00:00+00:00',
              endAt: '2026-11-03T01:30:00+00:00',
              note: null,
            },
          ],
        }),
      )
    })
  })

  it('renders an existing plan and can toggle a task', async () => {
    mockedPlans.get.mockResolvedValue(makePlan())
    mockedTasks.update.mockResolvedValue(makeTask({ status: 'completed' }))
    const onDataChanged = vi.fn()
    const user = userEvent.setup()
    renderWithApp(
      <TodayPage dataVersion={0} onDataChanged={onDataChanged} />,
    )

    expect(
      await screen.findByRole('checkbox', { name: /完成计划任务「写方案」/ }),
    ).toBeInTheDocument()
    const checkbox = screen.getByRole('checkbox', { name: /完成计划任务「写方案」/ })
    await user.click(checkbox)

    await waitFor(() => {
      expect(mockedTasks.update).toHaveBeenCalledWith('task-1', {
        status: 'completed',
      })
    })
    expect(onDataChanged).toHaveBeenCalled()
  })

  it('removes an item from an existing plan', async () => {
    mockedPlans.get.mockResolvedValue(makePlan())
    mockedPlans.save.mockResolvedValue({ ...makePlan(), items: [], plannedMinutes: 0 })
    const user = userEvent.setup()
    renderWithApp(<TodayPage dataVersion={0} onDataChanged={vi.fn()} />)

    await screen.findByRole('checkbox', { name: /完成计划任务「写方案」/ })
    await user.click(screen.getByRole('button', { name: '从计划中移除 写方案' }))

    await waitFor(() => {
      expect(mockedPlans.save).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({ items: [] }),
      )
    })
  })
})
