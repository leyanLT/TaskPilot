import { Checkbox } from 'antd'
import type { Plan } from '../types'
import { toAppTimezone } from '../utils/datetime'
import { PriorityTag } from './ui/PaperBits'

interface PlanTimelineProps {
  plan: Plan | null
  busyTaskId?: string | null
  onToggleTask?: (taskId: string, completed: boolean) => void
  onRemoveItem?: (itemId: string) => void
  emptyText?: string
}

export function PlanTimeline({
  plan,
  busyTaskId = null,
  onToggleTask,
  onRemoveItem,
  emptyText = '今天还没有计划，先排一个时间块吧。',
}: PlanTimelineProps) {
  if (!plan || plan.items.length === 0) {
    return <p className="muted-note">{emptyText}</p>
  }

  return (
    <div className="plan-timeline">
      <div className="plan-meta">
        <span>
          已安排 <strong>{plan.plannedMinutes}</strong> / {plan.availableMinutes} 分钟
        </span>
        <span className="plan-meta-note">时间按 {plan.timezone} 显示</span>
      </div>
      <ol className="plan-blocks">
        {plan.items.map((item) => {
          const start = toAppTimezone(item.startAt)
          const end = toAppTimezone(item.endAt)
          const completed = item.taskStatus === 'completed'
          return (
            <li
              key={item.id}
              className={`plan-block ${completed ? 'is-completed' : ''}`}
            >
              <span className="plan-time">
                {start.format('HH:mm')}
                <em>–</em>
                {end.format('HH:mm')}
              </span>
              <span className="plan-line" aria-hidden="true" />
              <div className="plan-copy">
                <div className="plan-title-line">
                  <strong>{item.taskTitle}</strong>
                  <PriorityTag priority={item.priority} subtle />
                  {completed ? <span className="pencil-tag is-done">已完成</span> : null}
                </div>
                {item.note ? <p className="plan-note">{item.note}</p> : null}
              </div>
              <span className="plan-actions">
                {onToggleTask ? (
                  <Checkbox
                    checked={completed}
                    disabled={busyTaskId === item.taskId}
                    aria-label={
                      completed
                        ? `将计划任务「${item.taskTitle}」恢复为待完成`
                        : `完成计划任务「${item.taskTitle}」`
                    }
                    onChange={() => onToggleTask(item.taskId, completed)}
                  />
                ) : null}
                {onRemoveItem ? (
                  <button
                    className="task-action danger"
                    type="button"
                    aria-label={`从计划中移除 ${item.taskTitle}`}
                    onClick={() => onRemoveItem(item.id)}
                  >
                    移除
                  </button>
                ) : null}
              </span>
            </li>
          )
        })}
      </ol>
    </div>
  )
}
