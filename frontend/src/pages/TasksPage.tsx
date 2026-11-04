import { Alert, App, Spin } from 'antd'
import { useMemo, useState } from 'react'
import { RecurrencePanel } from '../components/RecurrencePanel'
import { TaskFormModal } from '../components/TaskFormModal'
import { TaskList } from '../components/TaskList'
import { TaskStats } from '../components/TaskStats'
import {
  EmptyState,
  InlineError,
  PageHeader,
  SectionCard,
} from '../components/ui/PaperBits'
import { usePriorities } from '../hooks/usePriorities'
import { useTasks } from '../hooks/useTasks'
import { getApiErrorMessage } from '../services/http'
import { taskApi } from '../services/tasks'
import type {
  Project,
  Task,
  TaskFilter,
  TaskInput,
  TaskPriority,
  TaskSort,
} from '../types'
import { PRIORITY_LABELS } from '../types'
import { isTaskOverdue } from '../utils/datetime'

const FILTERS: Array<{ label: string; value: TaskFilter }> = [
  { label: '全部', value: 'all' },
  { label: '待完成', value: 'pending' },
  { label: '已完成', value: 'completed' },
]

const SORT_OPTIONS: Array<{ label: string; value: TaskSort }> = [
  { label: '最新创建', value: 'created_desc' },
  { label: '最早创建', value: 'created_asc' },
  { label: '最早截止', value: 'due_asc' },
  { label: '最晚截止', value: 'due_desc' },
  { label: '优先级', value: 'priority' },
]

const PRIORITY_FILTERS: Array<{ label: string; value: TaskPriority | 'all' }> = [
  { label: '全部优先级', value: 'all' },
  { label: '高', value: 'high' },
  { label: '中', value: 'medium' },
  { label: '弱', value: 'low' },
]

const PRIORITY_RANK: Record<TaskPriority, number> = { high: 0, medium: 1, low: 2 }

function padCount(value: number): string {
  return String(value).padStart(2, '0')
}

function sortTasks(tasks: Task[], sort: TaskSort): Task[] {
  const sorted = [...tasks]
  sorted.sort((first, second) => {
    if (sort === 'priority') {
      const byPriority = PRIORITY_RANK[first.priority] - PRIORITY_RANK[second.priority]
      if (byPriority !== 0) {
        return byPriority
      }
      return Date.parse(first.dueAt ?? '2999-01-01') - Date.parse(second.dueAt ?? '2999-01-01')
    }
    if (sort.startsWith('created')) {
      const delta = Date.parse(first.createdAt) - Date.parse(second.createdAt)
      return sort === 'created_desc' ? -delta : delta
    }
    if (!first.dueAt && !second.dueAt) {
      return Date.parse(second.createdAt) - Date.parse(first.createdAt)
    }
    if (!first.dueAt) return 1
    if (!second.dueAt) return -1
    const delta = Date.parse(first.dueAt) - Date.parse(second.dueAt)
    return sort === 'due_desc' ? -delta : delta
  })
  return sorted
}

interface TasksPageProps {
  projects: Project[]
  dataVersion: number
  onOpenTask: (taskId: string) => void
  onDataChanged: () => void
}

export function TasksPage({
  projects,
  dataVersion,
  onOpenTask,
  onDataChanged,
}: TasksPageProps) {
  const { message } = App.useApp()
  const {
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
  } = useTasks({ reloadKey: dataVersion })
  const {
    suggestions,
    loading: suggestionsLoading,
    error: suggestionsError,
    reload: reloadSuggestions,
  } = usePriorities(6, dataVersion)

  const [filter, setFilter] = useState<TaskFilter>('all')
  const [sort, setSort] = useState<TaskSort>('created_desc')
  const [projectFilter, setProjectFilter] = useState<string>('all')
  const [priorityFilter, setPriorityFilter] = useState<TaskPriority | 'all'>('all')
  const [modalOpen, setModalOpen] = useState(false)
  const [editingTask, setEditingTask] = useState<Task | null>(null)
  const [busyTaskId, setBusyTaskId] = useState<string | null>(null)
  const [expandedTaskId, setExpandedTaskId] = useState<string | null>(null)
  const [subtasks, setSubtasks] = useState<Record<string, Task[]>>({})
  const [applyingSuggestion, setApplyingSuggestion] = useState<string | null>(null)

  const stats = useMemo(() => {
    const pending = tasks.filter((task) => task.status === 'pending').length
    const completed = tasks.filter((task) => task.status === 'completed').length
    return {
      total: tasks.length,
      pending,
      completed,
      overdue: tasks.filter((task) => isTaskOverdue(task)).length,
    }
  }, [tasks])

  const visibleTasks = useMemo(() => {
    const filtered = tasks.filter((task) => {
      if (filter !== 'all' && task.status !== filter) {
        return false
      }
      if (projectFilter !== 'all' && task.projectId !== projectFilter) {
        return false
      }
      if (priorityFilter !== 'all' && task.priority !== priorityFilter) {
        return false
      }
      return true
    })
    return sortTasks(filtered, sort)
  }, [filter, projectFilter, priorityFilter, sort, tasks])

  const filterCounts: Record<TaskFilter, number> = {
    all: stats.total,
    pending: stats.pending,
    completed: stats.completed,
  }

  const openCreateModal = () => {
    setEditingTask(null)
    setModalOpen(true)
  }

  const openEditModal = (task: Task) => {
    setEditingTask(task)
    setModalOpen(true)
  }

  const closeModal = () => {
    setModalOpen(false)
    setEditingTask(null)
  }

  const handleSubmit = async (input: TaskInput) => {
    if (editingTask) {
      await editTask(editingTask.id, input)
      message.success('任务已更新。')
    } else {
      await createTask(input)
      message.success('任务已创建。')
    }
    closeModal()
    onDataChanged()
  }

  const handleToggle = async (task: Task) => {
    setBusyTaskId(task.id)
    try {
      const updated = await toggleTask(task)
      message.success(
        updated.status === 'completed' ? '任务已标记为完成。' : '任务已恢复为待完成。',
      )
      onDataChanged()
    } catch (toggleError) {
      message.error(getApiErrorMessage(toggleError))
    } finally {
      setBusyTaskId(null)
    }
  }

  const refreshSubtasks = async (parentId: string) => {
    const data = await taskApi.subtasks(parentId)
    setSubtasks((current) => ({ ...current, [parentId]: data }))
  }

  const handleToggleExpand = async (task: Task) => {
    if (expandedTaskId === task.id) {
      setExpandedTaskId(null)
      return
    }
    setExpandedTaskId(task.id)
    if (!subtasks[task.id]) {
      try {
        await refreshSubtasks(task.id)
      } catch (expandError) {
        message.error(getApiErrorMessage(expandError))
      }
    }
  }

  const handleToggleSubtask = async (subtask: Task) => {
    setBusyTaskId(subtask.id)
    try {
      await toggleSubtask(subtask)
      if (subtask.parentId) {
        await refreshSubtasks(subtask.parentId)
        onDataChanged()
      }
    } catch (toggleError) {
      message.error(getApiErrorMessage(toggleError))
    } finally {
      setBusyTaskId(null)
    }
  }

  const handleAddSubtask = async (parent: Task, title: string) => {
    try {
      await addSubtask(parent.id, { title })
      await refreshSubtasks(parent.id)
      onDataChanged()
    } catch (addError) {
      message.error(getApiErrorMessage(addError))
    }
  }

  const handleDeleteSubtask = async (subtask: Task) => {
    try {
      await taskApi.remove(subtask.id)
      if (subtask.parentId) {
        await refreshSubtasks(subtask.parentId)
      }
      await reload()
      onDataChanged()
      message.success('子任务已删除。')
    } catch (deleteError) {
      message.error(getApiErrorMessage(deleteError))
    }
  }

  const handleMoveSubtask = async (
    parent: Task,
    subtask: Task,
    direction: -1 | 1,
  ) => {
    const list = subtasks[parent.id] ?? []
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
        parent.id,
        reordered.map((item) => item.id),
      )
      await refreshSubtasks(parent.id)
    } catch (moveError) {
      message.error(getApiErrorMessage(moveError))
    }
  }

  const handleDelete = async (task: Task) => {
    try {
      await removeTask(task.id, task.subtaskCount > 0)
      message.success('任务已删除。')
      setExpandedTaskId((current) => (current === task.id ? null : current))
      onDataChanged()
    } catch (deleteError) {
      message.error(getApiErrorMessage(deleteError))
    }
  }

  const applySuggestion = async (taskId: string, priority: TaskPriority) => {
    setApplyingSuggestion(taskId)
    try {
      await taskApi.update(taskId, { priority })
      await reload()
      await reloadSuggestions()
      onDataChanged()
      message.success(`优先级已调整为「${PRIORITY_LABELS[priority]}」。`)
    } catch (applyError) {
      message.error(getApiErrorMessage(applyError))
    } finally {
      setApplyingSuggestion(null)
    }
  }

  const heroSubline =
    stats.pending > 0
      ? `还有 ${stats.pending} 件小事。先挑一件开始。`
      : '今天没有待办了，给自己留一点空白。'

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="MY TASKS / 我的手边事"
        title={
          <>
            今天要做的，
            <br />
            <span className="marker">一件一件来。</span>
          </>
        }
        description={heroSubline}
        actions={<TaskStats {...stats} />}
      />

      {error ? (
        <Alert
          className="paper-alert"
          type="error"
          showIcon
          title="任务加载失败"
          description={error}
          action={
            <button className="paper-inline-button" type="button" onClick={() => void reload()}>
              重新加载
            </button>
          }
        />
      ) : null}

      <div className="main-grid tasks-grid">
        <SectionCard
          no="01 /"
          title="任务清单"
          subtitle={`${visibleTasks.length} 件任务${
            stats.overdue > 0 ? ` · ${stats.overdue} 件逾期` : ' · 今天很稳'
          }${loading ? ' · 同步中…' : ''}`}
          actions={
            <div className="sheet-tools">
              <div className="paper-filters" role="group" aria-label="任务状态筛选">
                {FILTERS.map((item) => (
                  <button
                    className={`paper-filter ${filter === item.value ? 'active' : ''}`}
                    key={item.value}
                    type="button"
                    aria-label={`${item.label}，${filterCounts[item.value]} 个任务`}
                    aria-pressed={filter === item.value}
                    onClick={() => setFilter(item.value)}
                  >
                    {item.label}
                    <span>{padCount(filterCounts[item.value])}</span>
                  </button>
                ))}
              </div>
            </div>
          }
        >
          <div className="filter-row">
            <label className="sort-control">
              <span className="sort-prefix">项目</span>
              <select
                aria-label="按项目筛选"
                value={projectFilter}
                onChange={(event) => setProjectFilter(event.target.value)}
              >
                <option value="all">全部项目</option>
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="sort-control">
              <span className="sort-prefix">优先级</span>
              <select
                aria-label="按优先级筛选"
                value={priorityFilter}
                onChange={(event) =>
                  setPriorityFilter(event.target.value as TaskPriority | 'all')
                }
              >
                {PRIORITY_FILTERS.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="sort-control">
              <span className="sort-prefix">排序</span>
              <select
                aria-label="任务排序"
                value={sort}
                onChange={(event) => setSort(event.target.value as TaskSort)}
              >
                {SORT_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <button className="paper-inline-button" type="button" onClick={openCreateModal}>
              <span aria-hidden="true">＋</span> 新建任务
            </button>
          </div>

          {loading && tasks.length === 0 ? (
            <div className="center-state" aria-label="任务加载中">
              <Spin size="large" />
              <p>正在翻开今天的清单…</p>
            </div>
          ) : (
            <TaskList
              tasks={visibleTasks}
              busyTaskId={busyTaskId}
              projects={projects}
              subtasks={subtasks}
              expandedTaskId={expandedTaskId}
              onToggleExpand={(task) => void handleToggleExpand(task)}
              onToggleSubtask={(task) => void handleToggleSubtask(task)}
              onDeleteSubtask={(task) => void handleDeleteSubtask(task)}
              onAddSubtask={(task, title) => handleAddSubtask(task, title)}
              onMoveSubtask={(parent, task, direction) =>
                void handleMoveSubtask(parent, task, direction)
              }
              emptyContent={
                tasks.length === 0 ? (
                  <EmptyState
                    title="还没有任务，先创建第一个吧"
                    description="把想做的事写下来，纸会替你记住。"
                    action={
                      <button className="empty-action" type="button" onClick={openCreateModal}>
                        <span aria-hidden="true">＋</span> 创建第一个任务
                      </button>
                    }
                  />
                ) : (
                  <EmptyState
                    title="当前筛选下没有任务"
                    description="换一个项目或优先级筛选看看。"
                    action={
                      <button
                        className="empty-action"
                        type="button"
                        onClick={() => {
                          setFilter('all')
                          setProjectFilter('all')
                          setPriorityFilter('all')
                        }}
                      >
                        清除筛选
                      </button>
                    }
                  />
                )
              }
              onToggle={(task) => void handleToggle(task)}
              onEdit={openEditModal}
              onDelete={(task) => void handleDelete(task)}
            />
          )}
        </SectionCard>

        <aside className="tasks-aside">
          <SectionCard
            no="02 /"
            title="优先级建议"
            subtitle="由真实截止时间与项目日期计算"
            tone="sticky"
            actions={
              <button
                className="paper-inline-button"
                type="button"
                onClick={() => void reloadSuggestions()}
              >
                刷新
              </button>
            }
          >
            {suggestionsLoading ? (
              <div className="center-state small">
                <Spin size="small" />
                <p>正在计算…</p>
              </div>
            ) : null}
            {suggestionsError ? (
              <InlineError message={suggestionsError} onRetry={() => void reloadSuggestions()} />
            ) : null}
            {!suggestionsLoading && suggestions.length === 0 ? (
              <p className="muted-note">没有需要调整的待办任务。</p>
            ) : null}
            <ul className="suggestion-list">
              {suggestions.map((suggestion) => {
                const same = suggestion.currentPriority === suggestion.suggestedPriority
                return (
                  <li key={suggestion.taskId} className="suggestion-item">
                    <button
                      className="suggestion-title"
                      type="button"
                      onClick={() => onOpenTask(suggestion.taskId)}
                    >
                      {suggestion.title}
                    </button>
                    <div className="suggestion-meta">
                      <span className={`priority-pill priority-${suggestion.suggestedPriority}`}>
                        建议{PRIORITY_LABELS[suggestion.suggestedPriority]}
                      </span>
                      <span>当前{PRIORITY_LABELS[suggestion.currentPriority]}</span>
                      <span>得分 {suggestion.score}</span>
                    </div>
                    <ul className="suggestion-reasons">
                      {suggestion.reasons.map((reason) => (
                        <li key={reason}>{reason}</li>
                      ))}
                    </ul>
                    {!same ? (
                      <button
                        className="paper-inline-button"
                        type="button"
                        disabled={applyingSuggestion === suggestion.taskId}
                        onClick={() =>
                          void applySuggestion(
                            suggestion.taskId,
                            suggestion.suggestedPriority,
                          )
                        }
                      >
                        {applyingSuggestion === suggestion.taskId
                          ? '调整中…'
                          : '采用建议'}
                      </button>
                    ) : (
                      <span className="suggestion-ok">当前已是建议优先级</span>
                    )}
                  </li>
                )
              })}
            </ul>
          </SectionCard>

          <SectionCard no="03 /" title="重复任务" subtitle="按规则自动生成，不会重复">
            <RecurrencePanel dataVersion={dataVersion} />
          </SectionCard>

          <SectionCard no="04 /" title="小帮手" subtitle="拆解、规划、写报告">
            <p className="muted-note">
              复杂的任务可以交给 AI 先拆成小块；所有写入都会先等你确认。
            </p>
            <a className="paper-inline-button primary" href="#/assistant">
              打开 AI 助手
            </a>
          </SectionCard>
        </aside>
      </div>

      <TaskFormModal
        open={modalOpen}
        task={editingTask}
        projects={projects}
        onCancel={closeModal}
        onSubmit={handleSubmit}
      />
    </div>
  )
}
