import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ProjectsPage } from '../ProjectsPage'
import { projectApi } from '../../services/projects'
import { renderWithApp } from '../../test/render'
import { makeProject } from '../../test/fixtures'

vi.mock('../../services/projects', () => ({
  projectApi: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    archive: vi.fn(),
    restore: vi.fn(),
    get: vi.fn(),
  },
}))

const mockedProjects = vi.mocked(projectApi)

describe('ProjectsPage', () => {
  beforeEach(() => {
    mockedProjects.list.mockReset()
    mockedProjects.create.mockReset()
    mockedProjects.archive.mockReset()
  })

  it('lists real projects with progress and counts', async () => {
    mockedProjects.list.mockResolvedValue([
      makeProject({
        name: 'AI Agent 项目',
        stats: {
          totalTasks: 4,
          completedTasks: 2,
          pendingTasks: 2,
          overdueTasks: 1,
          completionRate: 50,
        },
      }),
    ])
    renderWithApp(
      <ProjectsPage dataVersion={0} onDataChanged={vi.fn()} onNavigate={vi.fn()} />,
    )

    expect(await screen.findByText('AI Agent 项目')).toBeInTheDocument()
    expect(screen.getByText('50%')).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: /完成率/ })).toHaveAttribute(
      'aria-valuenow',
      '50',
    )
    expect(screen.getByText('逾期 1')).toBeInTheDocument()
  })

  it('creates a project through the shared modal', async () => {
    mockedProjects.list.mockResolvedValue([])
    const created = makeProject({ id: 'new-project', name: '新项目' })
    mockedProjects.create.mockResolvedValue(created)
    const onDataChanged = vi.fn()
    const user = userEvent.setup()

    renderWithApp(
      <ProjectsPage
        dataVersion={0}
        onDataChanged={onDataChanged}
        onNavigate={vi.fn()}
      />,
    )

    await screen.findByText('还没有项目')
    await user.click(screen.getByRole('button', { name: '新建项目' }))
    await user.type(await screen.findByLabelText('项目名称'), '新项目')
    await user.click(screen.getByRole('button', { name: '创建项目' }))

    await waitFor(() => {
      expect(mockedProjects.create).toHaveBeenCalledWith(
        expect.objectContaining({
          name: '新项目',
          description: null,
          status: 'planning',
        }),
      )
    })
    expect(await screen.findByText('新项目')).toBeInTheDocument()
    expect(onDataChanged).toHaveBeenCalled()
  })

  it('requires a project name', async () => {
    mockedProjects.list.mockResolvedValue([])
    const user = userEvent.setup()
    renderWithApp(
      <ProjectsPage dataVersion={0} onDataChanged={vi.fn()} onNavigate={vi.fn()} />,
    )

    await user.click(await screen.findByRole('button', { name: '新建项目' }))
    await user.click(screen.getByRole('button', { name: '创建项目' }))
    expect(await screen.findByText('请输入项目名称')).toBeInTheDocument()
    expect(mockedProjects.create).not.toHaveBeenCalled()
  })

  it('archives a project and keeps it in the list', async () => {
    const project = makeProject({ id: 'archive-1', name: '待归档项目' })
    mockedProjects.list.mockResolvedValue([project])
    mockedProjects.archive.mockResolvedValue({
      ...project,
      status: 'archived',
    })
    const user = userEvent.setup()
    renderWithApp(
      <ProjectsPage dataVersion={0} onDataChanged={vi.fn()} onNavigate={vi.fn()} />,
    )

    await screen.findByText('待归档项目')
    await user.click(
      screen.getByRole('button', { name: '撕下归档项目「待归档项目」' }),
    )

    await waitFor(() => {
      expect(mockedProjects.archive).toHaveBeenCalledWith('archive-1')
    })
    expect((await screen.findAllByText('已归档')).length).toBeGreaterThan(0)
    expect(screen.getByText('待归档项目')).toBeInTheDocument()
    expect(await screen.findByTestId('project-note')).toHaveClass('is-torn')
    expect(
      screen.getByRole('button', { name: '贴回去项目「待归档项目」' }),
    ).toBeInTheDocument()
  })

  it('opens a project detail route', async () => {
    const project = makeProject({ id: 'open-1', name: '打开我' })
    mockedProjects.list.mockResolvedValue([project])
    const onNavigate = vi.fn()
    const user = userEvent.setup()
    renderWithApp(
      <ProjectsPage
        dataVersion={0}
        onDataChanged={vi.fn()}
        onNavigate={onNavigate}
      />,
    )

    await screen.findByText('打开我')
    await user.click(screen.getByRole('button', { name: '查看' }))
    expect(onNavigate).toHaveBeenCalledWith({ name: 'project', id: 'open-1' })
  })
})
