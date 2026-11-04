import { App, Spin } from 'antd'
import { useMemo, useState } from 'react'
import {
  EmptyState,
  InlineError,
  PageHeader,
  SectionCard,
} from '../components/ui/PaperBits'
import { useNotifications } from '../hooks/useNotifications'
import { getApiErrorMessage } from '../services/http'
import {
  NOTIFICATION_TYPE_LABELS,
  type AppNotification,
} from '../types'
import { formatDateTime } from '../utils/datetime'

interface NotificationsPageProps {
  dataVersion: number
  onOpenTask: (taskId: string) => void
  onDataChanged: () => void
}

const TYPE_HINT: Record<string, string> = {
  today_todo: '今天要记得',
  due_soon: '24 小时内到期',
  overdue: '已经逾期',
}

export function NotificationsPage({
  dataVersion,
  onOpenTask,
  onDataChanged,
}: NotificationsPageProps) {
  const { message } = App.useApp()
  const [filter, setFilter] = useState<'all' | 'unread'>('all')
  const {
    items,
    unreadCount,
    loading,
    error,
    reload,
    refresh,
    markRead,
    markAllRead,
  } = useNotifications(dataVersion)
  const [busyId, setBusyId] = useState<string | null>(null)

  const visible = useMemo(
    () => (filter === 'unread' ? items.filter((item) => !item.readAt) : items),
    [filter, items],
  )

  const openNotification = async (notification: AppNotification) => {
    setBusyId(notification.id)
    try {
      if (!notification.readAt) {
        await markRead(notification.id, true)
      }
      if (notification.taskId) {
        onOpenTask(notification.taskId)
      }
      onDataChanged()
    } catch (readError) {
      message.error(getApiErrorMessage(readError))
    } finally {
      setBusyId(null)
    }
  }

  const handleMarkAll = async () => {
    try {
      const count = await markAllRead()
      message.success(count > 0 ? `已标记 ${count} 条为已读。` : '没有未读提醒。')
      onDataChanged()
    } catch (markError) {
      message.error(getApiErrorMessage(markError))
    }
  }

  const handleRefresh = async () => {
    try {
      await refresh()
      message.success('提醒已重新同步。')
      onDataChanged()
    } catch (refreshError) {
      message.error(getApiErrorMessage(refreshError))
    }
  }

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="NOTIFICATIONS / 提醒中心"
        title={
          <>
            该看的，
            <br />
            <span className="marker">都在这里。</span>
          </>
        }
        description={`${unreadCount} 条未读 · 今日待办、即将截止与逾期提醒由真实任务生成。`}
        actions={
          <div className="hero-actions-row">
            <button className="paper-inline-button" type="button" onClick={() => void handleRefresh()}>
              重新同步
            </button>
            <button
              className="paper-inline-button"
              type="button"
              disabled={unreadCount === 0}
              onClick={() => void handleMarkAll()}
            >
              全部已读
            </button>
          </div>
        }
      />

      {error ? <InlineError message={error} onRetry={() => void reload()} /> : null}

      <SectionCard
        no="01 /"
        title="提醒列表"
        subtitle="已完成任务不会再出现未完成提醒"
        actions={
          <div className="paper-filters" role="group" aria-label="提醒筛选">
            <button
              className={`paper-filter ${filter === 'all' ? 'active' : ''}`}
              type="button"
              aria-pressed={filter === 'all'}
              onClick={() => setFilter('all')}
            >
              全部
              <span>{items.length}</span>
            </button>
            <button
              className={`paper-filter ${filter === 'unread' ? 'active' : ''}`}
              type="button"
              aria-pressed={filter === 'unread'}
              onClick={() => setFilter('unread')}
            >
              未读
              <span>{unreadCount}</span>
            </button>
          </div>
        }
      >
        {loading && items.length === 0 ? (
          <div className="center-state">
            <Spin size="large" />
            <p>正在整理提醒…</p>
          </div>
        ) : null}

        {!loading && visible.length === 0 ? (
          <EmptyState
            title={filter === 'unread' ? '没有未读提醒' : '还没有提醒'}
            description="当任务即将截止或逾期时，会自动出现在这里。"
          />
        ) : null}

        <ul className="notification-list">
          {visible.map((notification) => {
            const unread = !notification.readAt
            return (
              <li
                key={notification.id}
                className={`notification-item ${unread ? 'is-unread' : ''} type-${notification.type}`}
              >
                <span className="notification-dot" aria-hidden="true">
                  {unread ? '●' : '○'}
                </span>
                <button
                  className="notification-main"
                  type="button"
                  disabled={busyId === notification.id}
                  onClick={() => void openNotification(notification)}
                >
                  <span className="notification-type">
                    {NOTIFICATION_TYPE_LABELS[notification.type]}
                    <em>{TYPE_HINT[notification.type]}</em>
                  </span>
                  <span className="notification-message">{notification.message}</span>
                  <span className="notification-meta">
                    {notification.dueAt ? `截止 ${formatDateTime(notification.dueAt)} · ` : ''}
                    提醒生成 {formatDateTime(notification.createdAt)}
                  </span>
                </button>
                <div className="notification-actions">
                  {notification.taskId ? (
                    <button
                      className="task-action"
                      type="button"
                      aria-label={`查看提醒对应的任务 ${notification.taskTitle ?? ''}`}
                      onClick={() => void openNotification(notification)}
                    >
                      看任务
                    </button>
                  ) : null}
                  <button
                    className="task-action"
                    type="button"
                    aria-label={
                      unread
                        ? `标记提醒已读 ${notification.id}`
                        : `标记提醒未读 ${notification.id}`
                    }
                    onClick={async () => {
                      try {
                        await markRead(notification.id, unread)
                        onDataChanged()
                      } catch (markError) {
                        message.error(getApiErrorMessage(markError))
                      }
                    }}
                  >
                    {unread ? '标记已读' : '标记未读'}
                  </button>
                </div>
              </li>
            )
          })}
        </ul>
      </SectionCard>
    </div>
  )
}
