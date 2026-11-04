import { useCallback, useEffect, useState } from 'react'
import { getApiErrorMessage } from '../services/http'
import { taskApi } from '../services/tasks'
import type {
  SubtaskInput,
  Task,
  TaskInput,
  TaskPatch,
  TaskStatus,
} from '../types'

export interface UseTasksOptions {
  reloadKey?: number
  includeSubtasks?: boolean
}

export function useTasks(options: UseTasksOptions = {}) {
  const { reloadKey = 0, includeSubtasks = false } = options
  const [tasks, setTasks] = useState<Task[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const nextTasks = await taskApi.list({ includeSubtasks })
      setTasks(nextTasks)
      return true
    } catch (loadError) {
      setError(getApiErrorMessage(loadError))
      return false
    } finally {
      setLoading(false)
    }
  }, [includeSubtasks])

  useEffect(() => {
    let active = true
    taskApi
      .list({ includeSubtasks })
      .then((nextTasks) => {
        if (active) {
          setTasks(nextTasks)
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
  }, [reloadKey, includeSubtasks])

  const createTask = useCallback(async (input: TaskInput) => {
    const created = await taskApi.create(input)
    setTasks((current) => [created, ...current])
    return created
  }, [])

  const editTask = useCallback(async (taskId: string, patch: TaskPatch) => {
    const updated = await taskApi.update(taskId, patch)
    setTasks((current) =>
      current.map((task) => (task.id === taskId ? updated : task)),
    )
    return updated
  }, [])

  const toggleTask = useCallback(
    async (task: Task) => {
      const nextStatus: TaskStatus = task.status === 'pending' ? 'completed' : 'pending'
      return editTask(task.id, { status: nextStatus })
    },
    [editTask],
  )

  const removeTask = useCallback(
    async (taskId: string, confirmSubtasks = false) => {
      await taskApi.remove(taskId, confirmSubtasks)
      setTasks((current) => current.filter((task) => task.id !== taskId))
    },
    [],
  )

  const addSubtask = useCallback(
    async (parentId: string, input: SubtaskInput) => {
      const created = await taskApi.addSubtask(parentId, input)
      await reload()
      return created
    },
    [reload],
  )

  const toggleSubtask = useCallback(
    async (subtask: Task) => {
      const nextStatus: TaskStatus =
        subtask.status === 'pending' ? 'completed' : 'pending'
      const updated = await taskApi.update(subtask.id, { status: nextStatus })
      await reload()
      return updated
    },
    [reload],
  )

  return {
    tasks,
    loading,
    error,
    reload,
    createTask,
    editTask,
    toggleTask,
    removeTask,
    addSubtask,
    toggleSubtask,
  }
}

export type UseTasksResult = ReturnType<typeof useTasks>
