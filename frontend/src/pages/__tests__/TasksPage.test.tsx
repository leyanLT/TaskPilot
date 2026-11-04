import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TasksPage } from '../TasksPage'
import { taskApi } from '../../services/tasks'
import { insightApi } from '../../services/reports'
import { ApiError } from '../../services/http'
import { renderWithApp } from '../../test/render'
import { makeTask } from '../../test/fixtures'

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

vi.mock('../../services/reports', () => ({
  insightApi: {
    dashboard: vi.fn(),
    priorities: vi.fn(),
  },
  reportApi: {
    generate: vi.fn(),
    list: vi.fn(),
    get: vi.fn(),
    save: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    downloadMarkdown: vi.fn(),
  },
}))

const mockedTaskApi = vi.mocked(taskApi)
const mockedPriorities = vi.mocked(insightApi.priorities)

function renderPage(onDataChanged = vi.fn()) {
  return renderWithApp(
    <TasksPage
      projects={[]}
      dataVersion={0}
      onOpenTask={vi.fn()}
      onDataChanged={onDataChanged}
    />,
  )
}

describe('TasksPage', () => {
  beforeEach(() => {
    mockedTaskApi.list.mockReset()
    mockedTaskApi.create.mockReset()
    mockedTaskApi.update.mockReset()
    mockedTaskApi.remove.mockReset()
    mockedTaskApi.subtasks.mockReset()
    mockedTaskApi.addSubtask.mockReset()
    mockedTaskApi.reorderSubtasks.mockReset()
    mockedPriorities.mockReset()
    mockedPriorities.mockResolvedValue([])
  })

  it('loads tasks from the API and shows statistics', async () => {
    mockedTaskApi.list.mockResolvedValue([
      makeTask({ id: 'pending-1', title: '待办事项', status: 'pending' }),
      makeTask({ id: 'done-1', title: '完成事项', status: 'completed' }),
    ])
    renderPage()

    expect(await screen.findByText('待办事项')).toBeInTheDocument()
    expect(screen.getByText('完成事项')).toBeInTheDocument()
    expect(screen.getByText('全部任务')).toBeInTheDocument()
    expect(screen.getByText('已逾期')).toBeInTheDocument()
  })

  it('creates a task through the modal and immediately lists it', async () => {
    mockedTaskApi.list.mockResolvedValue([])
    const created = makeTask({ id: 'created-1', title: '写周报' })
    mockedTaskApi.create.mockResolvedValue(created)
    const onDataChanged = vi.fn()
    const user = userEvent.setup()
    renderPage(onDataChanged)

    await screen.findByText('还没有任务，先创建第一个吧')
    await user.click(screen.getByRole('button', { name: '新建任务' }))
    await user.type(await screen.findByLabelText('标题'), '写周报')
    await user.click(screen.getByRole('button', { name: '创建任务' }))

    await waitFor(() => {
      expect(mockedTaskApi.create).toHaveBeenCalledWith({
        title: '写周报',
        description: null,
        dueAt: null,
        projectId: null,
        priority: 'medium',
        estimatedMinutes: null,
      })
    })
    expect(await screen.findByText('写周报')).toBeInTheDocument()
    expect(onDataChanged).toHaveBeenCalled()
  })

  it('toggles a task status through the API', async () => {
    const pending = makeTask({ id: 'task-1', title: '需要完成', status: 'pending' })
    mockedTaskApi.list.mockResolvedValue([pending])
    mockedTaskApi.update.mockResolvedValue({ ...pending, status: 'completed' })
    const user = userEvent.setup()
    renderPage()

    const checkbox = await screen.findByRole('checkbox', { name: /标记为完成/ })
    await user.click(checkbox)

    await waitFor(() => {
      expect(mockedTaskApi.update).toHaveBeenCalledWith('task-1', {
        status: 'completed',
      })
    })
    expect(await screen.findByRole('checkbox', { name: /恢复为待完成/ })).toBeChecked()
  })

  it('deletes a task only after confirmation', async () => {
    const task = makeTask({ id: 'delete-1', title: '待删除任务' })
    mockedTaskApi.list.mockResolvedValue([task])
    mockedTaskApi.remove.mockResolvedValue(undefined)
    const user = userEvent.setup()
    renderPage()

    await screen.findByText('待删除任务')
    await user.click(screen.getByRole('button', { name: '删除任务 待删除任务' }))
    expect(mockedTaskApi.remove).not.toHaveBeenCalled()

    await user.click(await screen.findByRole('button', { name: '确认删除' }))
    await waitFor(() => {
      expect(mockedTaskApi.remove).toHaveBeenCalledWith('delete-1', false)
    })
    await waitFor(() => {
      expect(screen.queryByText('待删除任务')).not.toBeInTheDocument()
    })
  })

  it('offers a reload action when loading fails', async () => {
    mockedTaskApi.list
      .mockRejectedValueOnce(new ApiError('数据库连接失败', 'DATABASE_ERROR', 500))
      .mockResolvedValueOnce([makeTask({ title: '重试后的任务' })])
    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByText('任务加载失败')).toBeInTheDocument()
    expect(screen.getByText('数据库连接失败')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '重新加载' }))

    expect(await screen.findByText('重试后的任务')).toBeInTheDocument()
    expect(screen.queryByText('任务加载失败')).not.toBeInTheDocument()
  })

  it('filters tasks by status', async () => {
    mockedTaskApi.list.mockResolvedValue([
      makeTask({ id: 'pending-1', title: '待办任务', status: 'pending' }),
      makeTask({ id: 'done-1', title: '已完成任务', status: 'completed' }),
    ])
    const user = userEvent.setup()
    renderPage()

    await screen.findByText('待办任务')
    expect(screen.getByText('已完成任务')).toBeInTheDocument()

    const pendingFilter = screen.getByRole('button', { name: /^待完成/ })
    await user.click(pendingFilter)
    expect(pendingFilter).toHaveAttribute('aria-pressed', 'true')
    expect(screen.queryByText('已完成任务')).not.toBeInTheDocument()
    expect(screen.getByText('待办任务')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /^已完成/ }))
    expect(screen.queryByText('待办任务')).not.toBeInTheDocument()
    expect(screen.getByText('已完成任务')).toBeInTheDocument()
  })

  it('filters by project and priority', async () => {
    mockedTaskApi.list.mockResolvedValue([
      makeTask({
        id: 'high-project',
        title: '高优先级项目任务',
        projectId: 'project-a',
        priority: 'high',
      }),
      makeTask({ id: 'low-task', title: '低优先级任务', priority: 'low' }),
    ])
    const user = userEvent.setup()
    renderWithApp(
      <TasksPage
        projects={[
          {
            id: 'project-a',
            name: '项目甲',
            description: null,
            status: 'active',
            startDate: null,
            dueDate: null,
            createdAt: '2026-01-01T00:00:00+00:00',
            updatedAt: '2026-01-01T00:00:00+00:00',
            stats: {
              totalTasks: 1,
              completedTasks: 0,
              pendingTasks: 1,
              overdueTasks: 0,
              completionRate: 0,
            },
          },
        ]}
        dataVersion={0}
        onOpenTask={vi.fn()}
        onDataChanged={vi.fn()}
      />,
    )

    await screen.findByText('高优先级项目任务')
    await user.selectOptions(
      screen.getByRole('combobox', { name: '按项目筛选' }),
      'project-a',
    )
    expect(screen.queryByText('低优先级任务')).not.toBeInTheDocument()

    await user.selectOptions(
      screen.getByRole('combobox', { name: '按优先级筛选' }),
      'low',
    )
    expect(screen.queryByText('高优先级项目任务')).not.toBeInTheDocument()
  })

  it('sorts tasks by due date with the sort control', async () => {
    mockedTaskApi.list.mockResolvedValue([
      makeTask({
        id: 'no-due',
        title: '无截止',
        dueAt: null,
        createdAt: '2026-01-03T08:00:00+00:00',
      }),
      makeTask({
        id: 'later',
        title: '晚截止',
        dueAt: '2026-01-03T12:00:00+00:00',
        createdAt: '2026-01-02T08:00:00+00:00',
      }),
      makeTask({
        id: 'earlier',
        title: '早截止',
        dueAt: '2026-01-02T12:00:00+00:00',
        createdAt: '2026-01-01T08:00:00+00:00',
      }),
    ])
    const user = userEvent.setup()
    renderPage()

    await screen.findByText('无截止')
    await user.selectOptions(
      screen.getByRole('combobox', { name: '任务排序' }),
      'due_asc',
    )

    const rows = screen.getAllByRole('listitem')
    expect(within(rows[0]).getByText('早截止')).toBeInTheDocument()
    expect(within(rows[1]).getByText('晚截止')).toBeInTheDocument()
    expect(within(rows[2]).getByText('无截止')).toBeInTheDocument()
  })

  it('applies a priority suggestion', async () => {
    const task = makeTask({ id: 'suggest-1', title: '建议任务', priority: 'low' })
    mockedTaskApi.list.mockResolvedValue([task])
    mockedTaskApi.update.mockResolvedValue({ ...task, priority: 'high' })
    mockedPriorities.mockResolvedValue([
      {
        taskId: 'suggest-1',
        title: '建议任务',
        currentPriority: 'low',
        suggestedPriority: 'high',
        score: 72,
        reasons: ['任务已逾期', '预计耗时较短（30 分钟）'],
        dueAt: '2000-01-01T10:00:00+00:00',
        projectId: null,
        projectName: null,
        estimatedMinutes: 30,
      },
    ])
    const user = userEvent.setup()
    renderPage()

    await screen.findByText('优先级建议')
    expect(screen.getByText('任务已逾期')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '采用建议' }))

    await waitFor(() => {
      expect(mockedTaskApi.update).toHaveBeenCalledWith('suggest-1', {
        priority: 'high',
      })
    })
  })

  it('keeps the modal open and shows the API error when creation fails', async () => {
    mockedTaskApi.list.mockResolvedValue([])
    mockedTaskApi.create.mockRejectedValue(
      new ApiError('标题不符合要求', 'VALIDATION_ERROR', 422),
    )
    const user = userEvent.setup()
    renderPage()

    await screen.findByText('还没有任务，先创建第一个吧')
    await user.click(screen.getByRole('button', { name: '新建任务' }))
    await user.type(await screen.findByLabelText('标题'), '失败的任务')
    await user.click(screen.getByRole('button', { name: '创建任务' }))

    expect(await screen.findByText('标题不符合要求')).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('shows an empty state and can open the create modal', async () => {
    mockedTaskApi.list.mockResolvedValue([])
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole('button', { name: '创建第一个任务' }))
    expect(await screen.findByLabelText('标题')).toBeInTheDocument()
  })
})
