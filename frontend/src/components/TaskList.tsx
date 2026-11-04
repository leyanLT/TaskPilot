import { Checkbox, Popconfirm } from 'antd'
import type { ReactNode } from 'react'
import type { Project, Task } from '../types'
import { formatDateTime, formatDueLabel, isTaskOverdue } from '../utils/datetime'
import { PriorityTag, ProjectChip } from './ui/PaperBits'
import { SubtaskList } from './SubtaskList'

interface TaskListProps {
  tasks: Task[]
  busyTaskId: string | null
  emptyContent: ReactNode
  onToggle: (task: Task) => void
  onEdit: (task: Task) => void
  onDelete: (task: Task) => void
  projects?: Project[]
  subtasks?: Record<string, Task[]>
  expandedTaskId?: string | null
  onToggleExpand?: (task: Task) => void
  onToggleSubtask?: (task: Task) => void
  onDeleteSubtask?: (task: Task) => void
  onAddSubtask?: (task: Task, title: string) => Promise<unknown> | void
  onMoveSubtask?: (parent: Task, task: Task, direction: -1 | 1) => void
}

function projectName(projects: Project[] | undefined, projectId: string | null): string | null {
  if (!projectId || !projects) {
    return null
  }
  return projects.find((project) => project.id === projectId)?.name ?? null
}

export function TaskList({
  tasks,
  busyTaskId,
  emptyContent,
  onToggle,
  onEdit,
  onDelete,
  projects,
  subtasks,
  expandedTaskId,
  onToggleExpand,
  onToggleSubtask,
  onDeleteSubtask,
  onAddSubtask,
  onMoveSubtask,
}: TaskListProps) {
  if (tasks.length === 0) {
    return (
      <div className="task-empty">
        {emptyContent || <p className="empty-plain">暂无任务</p>}
      </div>
    )
  }

  return (
    <ul className="task-list" aria-label="任务列表">
      {tasks.map((task) => {
        const completed = task.status === 'completed'
        const overdue = isTaskOverdue(task)
        const dueNote = completed
          ? '已经做好啦'
          : overdue
            ? '已经晚了一点'
            : task.dueAt
              ? '还来得及'
              : '有空再说'
        const name = projectName(projects, task.projectId)
        const expanded = expandedTaskId === task.id
        const children = subtasks?.[task.id] ?? []

        return (
          <li
            key={task.id}
            className={`task-row ${completed ? 'is-completed' : ''} ${
              overdue ? 'is-overdue' : ''
            } ${expanded ? 'is-expanded' : ''}`}
          >
            <div className="task-main-line">
              <div className="task-checkbox-cell">
                <Checkbox
                  checked={completed}
                  disabled={busyTaskId === task.id}
                  aria-label={
                    completed
                      ? `将「${task.title}」恢复为待完成`
                      : `将「${task.title}」标记为完成`
                  }
                  onChange={() => onToggle(task)}
                />
              </div>

              <div className="task-copy">
                <div className="task-title-line">
                  <span className="task-title">{task.title}</span>
                  <PriorityTag priority={task.priority} />
                  {completed ? <span className="pencil-tag is-done">已完成</span> : null}
                  {overdue ? <span className="pencil-tag is-late">已逾期</span> : null}
                  {task.subtaskCount > 0 ? (
                    <span className="pencil-tag is-subtasks">
                      子任务 {task.completedSubtaskCount}/{task.subtaskCount}
                    </span>
                  ) : null}
                </div>
                <div className="task-meta-line">
                  {task.description ? <span className="task-sub">{task.description}</span> : null}
                  {name ? <ProjectChip name={name} /> : null}
                  {task.estimatedMinutes ? (
                    <span className="task-estimate">约 {task.estimatedMinutes} 分钟</span>
                  ) : null}
                </div>
              </div>

              <div
                className={`task-when ${overdue ? 'is-overdue' : ''}`}
                title={task.dueAt ? `截止 ${formatDateTime(task.dueAt)}` : '未设置截止时间'}
              >
                <strong>{formatDueLabel(task.dueAt)}</strong>
                <span>{dueNote}</span>
                {task.dueAt ? (
                  <span className="sr-only">截止 {formatDateTime(task.dueAt)}</span>
                ) : null}
              </div>

              <div className="task-actions">
                {task.subtaskCount > 0 && onToggleExpand ? (
                  <button
                    className="task-action"
                    type="button"
                    aria-label={`${expanded ? '收起' : '查看'}任务 ${task.title} 的子任务`}
                    onClick={() => onToggleExpand(task)}
                  >
                    {expanded ? '收起' : '子任务'}
                  </button>
                ) : null}
                <button
                  className="task-action"
                  type="button"
                  aria-label={`编辑任务 ${task.title}`}
                  onClick={() => onEdit(task)}
                >
                  编辑
                </button>
                <Popconfirm
                  title={task.subtaskCount > 0 ? '确认删除这个任务和它的子任务？' : '确认删除这个任务？'}
                  description={
                    task.subtaskCount > 0
                      ? `将同时删除 ${task.subtaskCount} 个子任务，删除后无法恢复。`
                      : '删除后无法恢复。'
                  }
                  okText="确认删除"
                  cancelText="再想想"
                  okButtonProps={{ danger: true }}
                  onConfirm={() => onDelete(task)}
                >
                  <button
                    className="task-action danger"
                    type="button"
                    aria-label={`删除任务 ${task.title}`}
                  >
                    删除
                  </button>
                </Popconfirm>
              </div>
            </div>

            {expanded && onToggleSubtask && onAddSubtask && onDeleteSubtask && onMoveSubtask ? (
              <SubtaskList
                parent={task}
                subtasks={children}
                busyTaskId={busyTaskId}
                onToggle={onToggleSubtask}
                onDelete={onDeleteSubtask}
                onAdd={(title) => onAddSubtask(task, title)}
                onMove={(subtask, direction) => onMoveSubtask(task, subtask, direction)}
              />
            ) : null}
          </li>
        )
      })}
    </ul>
  )
}
