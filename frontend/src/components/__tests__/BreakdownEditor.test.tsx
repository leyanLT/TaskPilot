import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BreakdownEditor } from '../ActionDrafts'
import { renderWithApp } from '../../test/render'
import { makeProject } from '../../test/fixtures'
import type { BreakdownDraft } from '../../types'

const breakdown: BreakdownDraft = {
  goal: '两周内完成 AI Agent 项目',
  projectId: null,
  projectName: null,
  tasks: [
    {
      title: '设计架构',
      description: null,
      priority: 'high',
      estimatedMinutes: 120,
      dueAt: null,
      subtasks: [
        {
          title: '列出工具',
          description: null,
          priority: 'medium',
          estimatedMinutes: 30,
          dueAt: null,
        },
      ],
    },
  ],
}

describe('BreakdownEditor', () => {
  it('lets the user edit titles and subtasks before confirming', async () => {
    const onConfirm = vi.fn()
    const user = userEvent.setup()
    renderWithApp(
      <BreakdownEditor
        breakdown={breakdown}
        projects={[makeProject({ id: 'project-1', name: '项目甲' })]}
        busy={false}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    )

    const titleInput = screen.getByLabelText('拆解任务 1 标题')
    await user.clear(titleInput)
    await user.type(titleInput, '设计并实现架构')

    const subtaskInput = screen.getByLabelText('拆解任务 1 子任务 1 标题')
    await user.clear(subtaskInput)
    await user.type(subtaskInput, '列出工具与状态')

    await user.click(screen.getByRole('button', { name: '确认并创建' }))

    expect(onConfirm).toHaveBeenCalledTimes(1)
    const draft = onConfirm.mock.calls[0][0] as BreakdownDraft
    expect(draft.tasks[0].title).toBe('设计并实现架构')
    expect(draft.tasks[0].subtasks[0].title).toBe('列出工具与状态')
  })

  it('adds a new parent task and a new subtask', async () => {
    const onConfirm = vi.fn()
    const user = userEvent.setup()
    renderWithApp(
      <BreakdownEditor
        breakdown={breakdown}
        projects={[]}
        busy={false}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    )

    await user.click(screen.getByRole('button', { name: /添加任务/ }))
    const newTitle = screen.getByLabelText('拆解任务 2 标题')
    await user.type(newTitle, '跑通端到端流程')

    const addSubtask = screen.getByLabelText('为拆解任务 2 添加子任务')
    await user.type(addSubtask, '写冒烟测试{Enter}')
    expect(screen.getByLabelText('拆解任务 2 子任务 1 标题')).toHaveValue('写冒烟测试')

    await user.click(screen.getByRole('button', { name: '确认并创建' }))
    const draft = onConfirm.mock.calls[0][0] as BreakdownDraft
    expect(draft.tasks).toHaveLength(2)
    expect(draft.tasks[1].title).toBe('跑通端到端流程')
    expect(draft.tasks[1].subtasks[0].title).toBe('写冒烟测试')
  })

  it('blocks confirmation while a title is empty', () => {
    renderWithApp(
      <BreakdownEditor
        breakdown={{
          ...breakdown,
          tasks: [{ ...breakdown.tasks[0], title: '' }],
        }}
        projects={[]}
        busy={false}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    )

    expect(screen.getByRole('button', { name: '确认并创建' })).toBeDisabled()
    expect(
      screen.getByText('请补全所有任务与子任务的标题后再确认。'),
    ).toBeInTheDocument()
  })
})
