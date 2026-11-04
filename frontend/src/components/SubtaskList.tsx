import { Checkbox, Popconfirm } from 'antd'
import { useState } from 'react'
import type { Task } from '../types'
import { formatDueLabel, isTaskOverdue } from '../utils/datetime'
import { PriorityTag } from './ui/PaperBits'

interface SubtaskListProps {
  parent: Task
  subtasks: Task[]
  busyTaskId: string | null
  onToggle: (task: Task) => void
  onDelete: (task: Task) => void
  onAdd: (title: string) => Promise<unknown> | void
  onMove: (task: Task, direction: -1 | 1) => void
}

export function SubtaskList({
  parent,
  subtasks,
  busyTaskId,
  onToggle,
  onDelete,
  onAdd,
  onMove,
}: SubtaskListProps) {
  const [title, setTitle] = useState('')
  const [adding, setAdding] = useState(false)

  const submit = async () => {
    const trimmed = title.trim()
    if (!trimmed || adding) {
      return
    }
    setAdding(true)
    try {
      await onAdd(trimmed)
      setTitle('')
    } finally {
      setAdding(false)
    }
  }

  return (
    <div className="subtask-panel" aria-label={`「${parent.title}」的子任务`}>
      {subtasks.length === 0 ? (
        <p className="muted-note">还没有子任务，可以把下一步拆细一点。</p>
      ) : (
        <ul className="subtask-list">
          {subtasks.map((subtask, index) => (
            <li
              key={subtask.id}
              className={`subtask-row ${subtask.status === 'completed' ? 'is-completed' : ''}`}
            >
              <Checkbox
                checked={subtask.status === 'completed'}
                disabled={busyTaskId === subtask.id}
                aria-label={
                  subtask.status === 'completed'
                    ? `将子任务「${subtask.title}」恢复为待完成`
                    : `将子任务「${subtask.title}」标记为完成`
                }
                onChange={() => onToggle(subtask)}
              />
              <span className="subtask-title">{subtask.title}</span>
              <PriorityTag priority={subtask.priority} subtle />
              <span className={`subtask-due ${isTaskOverdue(subtask) ? 'is-overdue' : ''}`}>
                {formatDueLabel(subtask.dueAt)}
              </span>
              {subtask.estimatedMinutes ? (
                <span className="subtask-estimate">{subtask.estimatedMinutes} 分钟</span>
              ) : null}
              <span className="subtask-order">
                <button
                  className="task-action"
                  type="button"
                  aria-label={`上移子任务 ${subtask.title}`}
                  disabled={index === 0}
                  onClick={() => onMove(subtask, -1)}
                >
                  ↑
                </button>
                <button
                  className="task-action"
                  type="button"
                  aria-label={`下移子任务 ${subtask.title}`}
                  disabled={index === subtasks.length - 1}
                  onClick={() => onMove(subtask, 1)}
                >
                  ↓
                </button>
                <Popconfirm
                  title="确认删除这个子任务？"
                  description="删除后无法恢复。"
                  okText="确认删除"
                  cancelText="再想想"
                  okButtonProps={{ danger: true }}
                  onConfirm={() => onDelete(subtask)}
                >
                  <button
                    className="task-action danger"
                    type="button"
                    aria-label={`删除子任务 ${subtask.title}`}
                  >
                    删除
                  </button>
                </Popconfirm>
              </span>
            </li>
          ))}
        </ul>
      )}

      <div className="subtask-add">
        <input
          className="paper-input"
          value={title}
          maxLength={100}
          placeholder="添加一个子任务…"
          aria-label={`为「${parent.title}」添加子任务`}
          onChange={(event) => setTitle(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.nativeEvent.isComposing) {
              event.preventDefault()
              void submit()
            }
          }}
        />
        <button
          className="paper-inline-button"
          type="button"
          disabled={adding || !title.trim()}
          onClick={() => void submit()}
        >
          {adding ? '添加中…' : '添加子任务'}
        </button>
      </div>
    </div>
  )
}
