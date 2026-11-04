import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TaskList } from '../TaskList'
import { renderWithApp } from '../../test/render'
import { makeTask } from '../../test/fixtures'

describe('TaskList', () => {
  const defaultProps = {
    busyTaskId: null,
    emptyContent: null,
    onToggle: vi.fn(),
    onEdit: vi.fn(),
    onDelete: vi.fn(),
  }

  it('shows an empty state when there are no tasks', () => {
    renderWithApp(<TaskList tasks={[]} {...defaultProps} />)
    expect(screen.getByText('暂无任务')).toBeInTheDocument()
  })

  it('renders status, due date, and overdue marker', () => {
    const overdueTask = makeTask({
      title: '过期任务',
      dueAt: '2000-01-01T10:00:00+00:00',
    })
    renderWithApp(<TaskList tasks={[overdueTask]} {...defaultProps} />)

    expect(screen.getByText('过期任务')).toBeInTheDocument()
    expect(screen.getByText('已逾期')).toBeInTheDocument()
    expect(screen.getByText(/截止 2000-01-01 18:00/)).toBeInTheDocument()
  })

  it('does not mark completed tasks as overdue', () => {
    const completed = makeTask({
      title: '已完成旧任务',
      status: 'completed',
      dueAt: '2000-01-01T10:00:00+00:00',
    })
    renderWithApp(<TaskList tasks={[completed]} {...defaultProps} />)

    expect(screen.getByText('已完成')).toBeInTheDocument()
    expect(screen.queryByText('已逾期')).not.toBeInTheDocument()
  })

  it('triggers toggle and edit callbacks', async () => {
    const user = userEvent.setup()
    const task = makeTask({ title: '交互任务' })
    const onToggle = vi.fn()
    const onEdit = vi.fn()

    renderWithApp(
      <TaskList
        tasks={[task]}
        {...defaultProps}
        onToggle={onToggle}
        onEdit={onEdit}
      />,
    )

    await user.click(screen.getByRole('checkbox', { name: /标记为完成/ }))
    expect(onToggle).toHaveBeenCalledWith(task)

    await user.click(screen.getByRole('button', { name: '编辑任务 交互任务' }))
    expect(onEdit).toHaveBeenCalledWith(task)
  })

  it('requires confirmation before deleting', async () => {
    const user = userEvent.setup()
    const task = makeTask({ title: '删除测试' })
    const onDelete = vi.fn()

    renderWithApp(
      <TaskList tasks={[task]} {...defaultProps} onDelete={onDelete} />,
    )

    await user.click(screen.getByRole('button', { name: '删除任务 删除测试' }))
    expect(onDelete).not.toHaveBeenCalled()

    const confirmButton = await screen.findByRole('button', { name: '确认删除' })
    await user.click(confirmButton)

    await waitFor(() => {
      expect(onDelete).toHaveBeenCalledWith(task)
    })
  })

  it('cancel on delete confirmation has no side effect', async () => {
    const user = userEvent.setup()
    const onDelete = vi.fn()
    renderWithApp(
      <TaskList
        tasks={[makeTask({ title: '不要删除' })]}
        {...defaultProps}
        onDelete={onDelete}
      />,
    )

    await user.click(screen.getByRole('button', { name: '删除任务 不要删除' }))
    const dialog = await screen.findByText('确认删除这个任务？')
    expect(dialog).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '再想想' }))
    expect(onDelete).not.toHaveBeenCalled()
  })

  it('disables the checkbox for a busy task', () => {
    renderWithApp(
      <TaskList
        tasks={[makeTask()]}
        {...defaultProps}
        busyTaskId="task-1"
      />,
    )
    expect(screen.getByRole('checkbox')).toBeDisabled()
  })
})
