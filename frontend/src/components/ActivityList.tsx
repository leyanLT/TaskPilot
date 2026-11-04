import type { Activity } from '../types'
import { formatDateTime } from '../utils/datetime'

const ACTION_MARK: Record<string, string> = {
  task_created: '＋',
  task_updated: '✎',
  task_completed: '✓',
  task_reopened: '↺',
  task_deleted: '×',
  task_project_changed: '▤',
  subtask_created: '⤷',
  project_created: '▤',
  project_updated: '✎',
  project_status_changed: '⇄',
}

export function ActivityList({
  activities,
  emptyText = '还没有活动记录。',
  limit,
}: {
  activities: Activity[]
  emptyText?: string
  limit?: number
}) {
  const visible = limit ? activities.slice(0, limit) : activities
  if (visible.length === 0) {
    return <p className="muted-note">{emptyText}</p>
  }
  return (
    <ul className="activity-list" aria-label="最近活动">
      {visible.map((activity) => (
        <li key={activity.id} className="activity-item">
          <span className={`activity-mark action-${activity.action}`} aria-hidden="true">
            {ACTION_MARK[activity.action] ?? '·'}
          </span>
          <div className="activity-copy">
            <p>{activity.summary}</p>
            <small>
              {activity.projectName ? `${activity.projectName} · ` : ''}
              {formatDateTime(activity.createdAt)}
            </small>
          </div>
        </li>
      ))}
    </ul>
  )
}
