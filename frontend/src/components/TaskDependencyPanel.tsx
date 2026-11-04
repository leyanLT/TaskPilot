/* oxlint-disable react/set-state-in-effect -- data loading on mount; state is set after the request resolves. */
import { App, Spin } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { getApiErrorMessage } from '../services/http'
import { dependencyApi } from '../services/v2'
import { taskApi } from '../services/tasks'
import type { Task } from '../types'
import type { TaskDependencies } from '../types/v2'

export function TaskDependencyPanel({
  taskId,
  projectId,
  onChanged,
}: {
  taskId: string
  projectId: string | null
  onChanged: () => void
}) {
  const { message } = App.useApp()
  const [data, setData] = useState<TaskDependencies | null>(null)
  const [candidates, setCandidates] = useState<Task[]>([])
  const [selected, setSelected] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      const [dependencies, pending] = await Promise.all([
        dependencyApi.get(taskId),
        taskApi.list({ status: 'pending' }),
      ])
      setData(dependencies)
      setCandidates(
        pending.filter(
          (task) =>
            task.id !== taskId &&
            task.parentId === null &&
            task.projectId === projectId &&
            !dependencies.dependsOn.some((link) => link.dependsOnTaskId === task.id),
        ),
      )
      setSelected('')
    } catch (error) {
      message.error(getApiErrorMessage(error))
    } finally {
      setLoading(false)
    }
  }, [message, projectId, taskId])

  useEffect(() => {
    void load()
  }, [load])

  const add = async () => {
    if (!selected) {
      return
    }
    setBusy(true)
    try {
      await dependencyApi.add(taskId, selected)
      message.success('已添加前置任务。')
      await load()
      onChanged()
    } catch (error) {
      message.error(getApiErrorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  const remove = async (dependencyId: string) => {
    setBusy(true)
    try {
      await dependencyApi.remove(taskId, dependencyId)
      message.success('依赖已解除。')
      await load()
      onChanged()
    } catch (error) {
      message.error(getApiErrorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  if (loading) {
    return (
      <div className="center-state small">
        <Spin size="small" />
        <p>正在读取依赖…</p>
      </div>
    )
  }

  return (
    <div className="dependency-panel">
      {data?.isBlocked ? (
        <p className="dependency-blocked" role="status">
          前置任务还没完成，这个任务暂时不能标记完成。
        </p>
      ) : null}

      <h4 className="detail-subhead">前置任务</h4>
      {data && data.dependsOn.length > 0 ? (
        <ul className="dependency-list">
          {data.dependsOn.map((link) => (
            <li key={link.id}>
              <span className={`dependency-status ${link.dependsOnStatus}`}>
                {link.dependsOnStatus === 'completed' ? '已完成' : '未完成'}
              </span>
              <span className="dependency-title">{link.dependsOnTitle}</span>
              <button
                className="task-action danger"
                type="button"
                aria-label={`解除对「${link.dependsOnTitle}」的依赖`}
                disabled={busy}
                onClick={() => void remove(link.id)}
              >
                解除
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted-note">没有前置任务。</p>
      )}

      <div className="dependency-add">
        <select
          aria-label="选择前置任务"
          value={selected}
          onChange={(event) => setSelected(event.target.value)}
        >
          <option value="">添加一个前置任务…</option>
          {candidates.map((task) => (
            <option key={task.id} value={task.id}>
              {task.title}
            </option>
          ))}
        </select>
        <button
          className="paper-inline-button"
          type="button"
          disabled={busy || !selected}
          onClick={() => void add()}
        >
          添加
        </button>
      </div>

      {data && data.blocks.length > 0 ? (
        <>
          <h4 className="detail-subhead">这些任务在等它</h4>
          <ul className="dependency-list">
            {data.blocks.map((link) => (
              <li key={link.id}>
                <span className="dependency-title">{link.dependsOnTitle}</span>
              </li>
            ))}
          </ul>
        </>
      ) : null}
      <p className="muted-note">依赖只能建立在同一项目（或都没有项目）的任务之间。</p>
    </div>
  )
}
