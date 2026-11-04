import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TaskFormModal } from '../TaskFormModal'
import { renderWithApp } from '../../test/render'
import { makeTask } from '../../test/fixtures'

describe('TaskFormModal', () => {
  it('validates that a non-empty title is required', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn().mockResolvedValue(undefined)

    renderWithApp(
      <TaskFormModal open task={null} onCancel={vi.fn()} onSubmit={onSubmit} />,
    )

    await user.click(screen.getByRole('button', { name: '创建任务' }))

    expect(await screen.findByText('请输入任务标题')).toBeInTheDocument()
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('rejects a title made only of spaces', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn().mockResolvedValue(undefined)

    renderWithApp(
      <TaskFormModal open task={null} onCancel={vi.fn()} onSubmit={onSubmit} />,
    )

    await user.type(screen.getByLabelText('标题'), '   ')
    await user.click(screen.getByRole('button', { name: '创建任务' }))

    expect(await screen.findByText('请输入任务标题')).toBeInTheDocument()
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('submits trimmed values and never calls cancel on save', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    const onCancel = vi.fn()

    renderWithApp(
      <TaskFormModal open task={null} onCancel={onCancel} onSubmit={onSubmit} />,
    )

    await user.type(screen.getByLabelText('标题'), '  写周报  ')
    await user.type(screen.getByLabelText('描述'), '  本周进展  ')
    await user.click(screen.getByRole('button', { name: '创建任务' }))

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith({
        title: '写周报',
        description: '本周进展',
        dueAt: null,
        projectId: null,
        priority: 'medium',
        estimatedMinutes: null,
      })
    })
    expect(onCancel).not.toHaveBeenCalled()
  })

  it('cancel invokes onCancel without submitting data', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    const onCancel = vi.fn()

    renderWithApp(
      <TaskFormModal open task={null} onCancel={onCancel} onSubmit={onSubmit} />,
    )

    await user.type(screen.getByLabelText('标题'), '不会保存')
    await user.click(screen.getByRole('button', { name: '取消' }))

    expect(onCancel).toHaveBeenCalledTimes(1)
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('prefills fields when editing a task', async () => {
    renderWithApp(
      <TaskFormModal
        open
        task={makeTask({
          title: '已有任务',
          description: '已有描述',
          dueAt: '2026-11-04T07:00:00+00:00',
          priority: 'high',
          estimatedMinutes: 45,
        })}
        onCancel={vi.fn()}
        onSubmit={vi.fn().mockResolvedValue(undefined)}
      />,
    )

    expect(screen.getByLabelText('标题')).toHaveValue('已有任务')
    expect(screen.getByLabelText('描述')).toHaveValue('已有描述')
    expect(screen.getByRole('button', { name: '保存修改' })).toBeInTheDocument()
  })
})
