import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { NotificationsPage } from '../NotificationsPage'
import { notificationApi } from '../../services/notifications'
import { renderWithApp } from '../../test/render'

vi.mock('../../services/notifications', () => ({
  notificationApi: {
    list: vi.fn(),
    unreadCount: vi.fn(),
    refresh: vi.fn(),
    markRead: vi.fn(),
    markAllRead: vi.fn(),
  },
}))

const mockedNotifications = vi.mocked(notificationApi)

function makeNotification(overrides: Record<string, unknown> = {}) {
  return {
    id: 'notification-1',
    type: 'overdue' as const,
    taskId: 'task-1',
    taskTitle: '逾期任务',
    message: '「逾期任务」已于 11月02日 09:00 逾期',
    dueAt: '2026-11-02T01:00:00+00:00',
    createdAt: '2026-11-03T00:00:00+00:00',
    readAt: null,
    ...overrides,
  }
}

function renderPage(onOpenTask = vi.fn(), onDataChanged = vi.fn()) {
  return renderWithApp(
    <NotificationsPage
      dataVersion={0}
      onOpenTask={onOpenTask}
      onDataChanged={onDataChanged}
    />,
  )
}

describe('NotificationsPage', () => {
  beforeEach(() => {
    mockedNotifications.list.mockReset()
    mockedNotifications.markRead.mockReset()
    mockedNotifications.markAllRead.mockReset()
    mockedNotifications.refresh.mockReset()
  })

  it('marks a reminder read and opens the matching task', async () => {
    mockedNotifications.list.mockResolvedValue({
      items: [makeNotification()],
      unreadCount: 1,
    })
    mockedNotifications.markRead.mockResolvedValue(
      makeNotification({ readAt: '2026-11-03T01:00:00+00:00' }),
    )
    const onOpenTask = vi.fn()
    const onDataChanged = vi.fn()
    const user = userEvent.setup()
    renderPage(onOpenTask, onDataChanged)

    expect(await screen.findByText('「逾期任务」已于 11月02日 09:00 逾期')).toBeInTheDocument()
    await user.click(
      screen.getByRole('button', { name: /查看提醒对应的任务/ }),
    )

    await waitFor(() => {
      expect(mockedNotifications.markRead).toHaveBeenCalledWith('notification-1', true)
      expect(onOpenTask).toHaveBeenCalledWith('task-1')
    })
    expect(onDataChanged).toHaveBeenCalled()
  })

  it('marks all reminders as read', async () => {
    mockedNotifications.list.mockResolvedValue({
      items: [makeNotification()],
      unreadCount: 1,
    })
    mockedNotifications.markAllRead.mockResolvedValue(1)
    const user = userEvent.setup()
    renderPage()

    await screen.findByText('「逾期任务」已于 11月02日 09:00 逾期')
    await user.click(screen.getByRole('button', { name: '全部已读' }))

    await waitFor(() => {
      expect(mockedNotifications.markAllRead).toHaveBeenCalled()
    })
    expect(await screen.findByText('已标记 1 条为已读。')).toBeInTheDocument()
  })

  it('filters unread reminders and shows the empty state', async () => {
    mockedNotifications.list.mockResolvedValue({
      items: [makeNotification({ readAt: '2026-11-03T01:00:00+00:00' })],
      unreadCount: 0,
    })
    const user = userEvent.setup()
    renderPage()

    await screen.findByText('「逾期任务」已于 11月02日 09:00 逾期')
    await user.click(screen.getByRole('button', { name: /^未读/ }))
    expect(await screen.findByText('没有未读提醒')).toBeInTheDocument()
  })
})
