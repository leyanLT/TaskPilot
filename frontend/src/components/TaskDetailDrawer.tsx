import { Drawer, Spin } from 'antd'
import { useEffect, useState } from 'react'
import { getApiErrorMessage } from '../services/http'
import { taskApi } from '../services/tasks'
import type { Project, Task, TaskDetail } from '../types'
import { formatDateTime, formatDueLabel, isTaskOverdue } from '../utils/datetime'
import { SubtaskList } from './SubtaskList'
import { TaskDependencyPanel } from './TaskDependencyPanel'
import { PriorityTag, ProgressBar, ProjectChip } from './ui/PaperBits'

interface TaskDetailDrawerProps {
  taskId: string | null
  onClose: () => void
  projects: Project[]
  onEdit: (task: TaskDetail) => void
  onChanged: () => void
}

export function TaskDetailDrawer({
  taskId,
  onClose,
  projects,
  onEdit,
  onChanged,
}: TaskDetailDrawerProps) {
  const [detail, setDetail] = useState<TaskDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busySubtaskId, setBusySubtaskId] = useState<string | null>(null)

  useEffect(() => {
    if (!taskId) {
      return
    }
    let active = true
    taskApi
      .detail(taskId)
      .then((data) => {
        if (active) {
          setDetail(data)
          setError(null)
        }
      })
      .catch((loadError: unknown) => {
        if (active) {
          setError(getApiErrorMessage(loadError))
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false)
        }
      })
    return () => {
      active = false
    }
  }, [taskId])

  const openDetail = detail && detail.id === taskId ? detail : null

  const refreshDetail = async (id: string) => {
    const refreshed = await taskApi.detail(id)
    setDetail(refreshed)
  }

  const toggleSubtask = async (subtask: Task) => {
    if (!openDetail || busySubtaskId) {
      return
    }
    setBusySubtaskId(subtask.id)
    try {
      await taskApi.update(subtask.id, {
        status: subtask.status === 'completed' ? 'pending' : 'completed',
      })
      await refreshDetail(openDetail.id)
      onChanged()
    } catch (toggleError) {
      setError(getApiErrorMessage(toggleError))
    } finally {
      setBusySubtaskId(null)
    }
  }

  const addSubtask = async (title: string) => {
    if (!openDetail) {
      return
    }
    try {
      await taskApi.addSubtask(openDetail.id, { title })
      await refreshDetail(openDetail.id)
      onChanged()
    } catch (addError) {
      setError(getApiErrorMessage(addError))
    }
  }

  const deleteSubtask = async (subtask: Task) => {
    if (!openDetail) {
      return
    }
    try {
      await taskApi.remove(subtask.id)
      await refreshDetail(openDetail.id)
      onChanged()
    } catch (deleteError) {
      setError(getApiErrorMessage(deleteError))
    }
  }

  const moveSubtask = async (subtask: Task, direction: -1 | 1) => {
    if (!openDetail) {
      return
    }
    const list = openDetail.subtasks
    const index = list.findIndex((item) => item.id === subtask.id)
    const target = index + direction
    if (index < 0 || target < 0 || target >= list.length) {
      return
    }
    const reordered = [...list]
    const [moved] = reordered.splice(index, 1)
    reordered.splice(target, 0, moved)
    try {
      await taskApi.reorderSubtasks(
        openDetail.id,
        reordered.map((item) => item.id),
      )
      await refreshDetail(openDetail.id)
    } catch (moveError) {
      setError(getApiErrorMessage(moveError))
    }
  }

  const project = openDetail?.projectId
    ? projects.find((item) => item.id === openDetail.projectId)
    : null
  const percent =
    openDetail && openDetail.subtaskCount > 0
      ? (openDetail.completedSubtaskCount / openDetail.subtaskCount) * 100
      : openDetail?.status === 'completed'
        ? 100
        : 0

  return (
    <Drawer
      open={taskId !== null}
      onClose={onClose}
      size={460}
      className="paper-drawer"
      rootClassName="paper-drawer-root"
      title={
        <div className="modal-title-wrap">
          <span className="modal-eyebrow">TASK DETAIL</span>
          <span>任务详情</span>
        </div>
      }
    >
      {!openDetail && !error ? (
        <div className="center-state">
          <Spin />
          <p>{loading ? '正在翻开这一页…' : '正在读取任务…'}</p>
        </div>
      ) : null}
      {error ? (
        <div className="inline-error" role="alert">
          {error}
        </div>
      ) : null}
      {openDetail ? (
        <div className="task-detail">
          <h3 className="task-detail-title">{openDetail.title}</h3>
          <div className="task-detail-tags">
            <PriorityTag priority={openDetail.priority} />
            {project ? <ProjectChip name={project.name} status={project.status} /> : null}
            {openDetail.status === 'completed' ? (
              <span className="pencil-tag is-done">已完成</span>
            ) : null}
            {isTaskOverdue(openDetail) ? (
              <span className="pencil-tag is-late">已逾期</span>
            ) : null}
          </div>

          {openDetail.description ? (
            <p className="task-detail-description">{openDetail.description}</p>
          ) : null}

          <dl className="task-detail-facts">
            <div>
              <dt>截止时间</dt>
              <dd>{openDetail.dueAt ? formatDateTime(openDetail.dueAt) : '未设置'}</dd>
            </div>
            <div>
              <dt>预计耗时</dt>
              <dd>
                {openDetail.estimatedMinutes
                  ? `${openDetail.estimatedMinutes} 分钟`
                  : '未填写'}
              </dd>
            </div>
            <div>
              <dt>完成时间</dt>
              <dd>{openDetail.completedAt ? formatDateTime(openDetail.completedAt) : '尚未完成'}</dd>
            </div>
            <div>
              <dt>创建时间</dt>
              <dd>{formatDateTime(openDetail.createdAt)}</dd>
            </div>
          </dl>

          {openDetail.parent ? (
            <p className="muted-note">
              属于父任务「{openDetail.parent.title}」，截止{' '}
              {formatDueLabel(openDetail.parent.dueAt)}
            </p>
          ) : null}

          {openDetail.parentId ? null : (
            <div className="task-detail-subtasks">
              <div className="task-detail-progress">
                <span>
                  子任务 {openDetail.completedSubtaskCount}/{openDetail.subtaskCount}
                </span>
                <ProgressBar percent={percent} label="子任务完成进度" tone="green" />
              </div>
              <SubtaskList
                parent={openDetail}
                subtasks={openDetail.subtasks}
                busyTaskId={busySubtaskId}
                onToggle={(subtask) => void toggleSubtask(subtask)}
                onDelete={(subtask) => void deleteSubtask(subtask)}
                onAdd={(title) => addSubtask(title)}
                onMove={(subtask, direction) => void moveSubtask(subtask, direction)}
              />
            </div>
          )}

          {openDetail.parentId ? null : (
            <TaskDependencyPanel
              taskId={openDetail.id}
              projectId={openDetail.projectId}
              onChanged={onChanged}
            />
          )}

          <div className="task-detail-actions">
            <button
              className="paper-inline-button primary"
              type="button"
              onClick={() => onEdit(openDetail)}
            >
              编辑任务
            </button>
            <button className="paper-inline-button" type="button" onClick={onClose}>
              关闭
            </button>
          </div>
        </div>
      ) : null}
    </Drawer>
  )
}
