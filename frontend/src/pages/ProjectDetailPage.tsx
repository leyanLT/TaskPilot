import { App, Spin } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { ActivityList } from '../components/ActivityList'
import { ProjectFormModal } from '../components/ProjectFormModal'
import { TaskFormModal } from '../components/TaskFormModal'
import { TaskList } from '../components/TaskList'
import {
  EmptyState,
  InlineError,
  PageHeader,
  ProgressBar,
  SectionCard,
  StatTile,
} from '../components/ui/PaperBits'
import { getApiErrorMessage } from '../services/http'
import { projectApi } from '../services/projects'
import { taskApi } from '../services/tasks'
import {
  PROJECT_STATUS_LABELS,
  type AppRoute,
  type Project,
  type ProjectDetail,
  type ProjectInput,
  type Task,
  type TaskInput,
} from '../types'

interface ProjectDetailPageProps {
  projectId: string
  projects: Project[]
  dataVersion: number
  onDataChanged: () => void
  onNavigate: (route: AppRoute) => void
}

export function ProjectDetailPage({
  projectId,
  projects,
  dataVersion,
  onDataChanged,
  onNavigate,
}: ProjectDetailPageProps) {
  void dataVersion
  const { message } = App.useApp()
  const [detail, setDetail] = useState<ProjectDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [projectModalOpen, setProjectModalOpen] = useState(false)
  const [taskModalOpen, setTaskModalOpen] = useState(false)
  const [editingTask, setEditingTask] = useState<Task | null>(null)
  const [busyTaskId, setBusyTaskId] = useState<string | null>(null)
  const [archiving, setArchiving] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await projectApi.get(projectId)
      setDetail(data)
      return data
    } catch (loadError) {
      setError(getApiErrorMessage(loadError))
      return null
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    let active = true
    projectApi
      .get(projectId)
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
  }, [projectId])

  const refresh = async () => {
    await load()
    onDataChanged()
  }

  const toggleTask = async (task: Task) => {
    setBusyTaskId(task.id)
    try {
      await taskApi.update(task.id, {
        status: task.status === 'completed' ? 'pending' : 'completed',
      })
      await refresh()
      message.success(
        task.status === 'completed' ? '任务已恢复为待完成。' : '任务已标记为完成。',
      )
    } catch (toggleError) {
      message.error(getApiErrorMessage(toggleError))
    } finally {
      setBusyTaskId(null)
    }
  }

  const deleteTask = async (task: Task) => {
    try {
      await taskApi.remove(task.id, task.subtaskCount > 0)
      await refresh()
      message.success('任务已删除。')
    } catch (deleteError) {
      message.error(getApiErrorMessage(deleteError))
    }
  }

  const submitTask = async (input: TaskInput) => {
    if (!detail) {
      return
    }
    if (editingTask) {
      await taskApi.update(editingTask.id, input)
      message.success('任务已更新。')
    } else {
      await taskApi.create({ ...input, projectId: detail.project.id })
      message.success('任务已创建。')
    }
    setTaskModalOpen(false)
    setEditingTask(null)
    await refresh()
  }

  const submitProject = async (input: ProjectInput) => {
    if (!detail) {
      return
    }
    await projectApi.update(detail.project.id, input)
    setProjectModalOpen(false)
    await refresh()
    message.success('项目已更新。')
  }

  const toggleArchive = async () => {
    if (!detail) {
      return
    }
    setArchiving(true)
    try {
      if (detail.project.status === 'archived') {
        await projectApi.restore(detail.project.id)
        message.success('项目已恢复为进行中。')
      } else {
        await projectApi.archive(detail.project.id)
        message.success('项目已归档，历史任务与活动保持不变。')
      }
      await refresh()
    } catch (archiveError) {
      message.error(getApiErrorMessage(archiveError))
    } finally {
      setArchiving(false)
    }
  }

  if (loading && !detail) {
    return (
      <div className="center-state page-state">
        <Spin size="large" />
        <p>正在打开项目夹…</p>
      </div>
    )
  }

  if (error && !detail) {
    return (
      <div className="page-state">
        <InlineError message={error} onRetry={() => void load()} />
        <button
          className="paper-inline-button"
          type="button"
          onClick={() => onNavigate({ name: 'projects' })}
        >
          返回项目列表
        </button>
      </div>
    )
  }

  if (!detail) {
    return null
  }

  const { project, tasks, recentActivities } = detail
  const overdue = project.stats.overdueTasks

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow={`PROJECT / ${PROJECT_STATUS_LABELS[project.status]}`}
        title={project.name}
        description={project.description ?? '还没有项目描述。'}
        actions={
          <div className="hero-actions-row">
            <button
              className="paper-inline-button primary"
              type="button"
              onClick={() => {
                setEditingTask(null)
                setTaskModalOpen(true)
              }}
            >
              ＋ 添加任务
            </button>
            <button
              className="paper-inline-button"
              type="button"
              onClick={() => setProjectModalOpen(true)}
            >
              编辑项目
            </button>
            <button
              className="paper-inline-button"
              type="button"
              disabled={archiving}
              onClick={() => void toggleArchive()}
            >
              {project.status === 'archived' ? '恢复项目' : '归档'}
            </button>
            <button
              className="paper-inline-button"
              type="button"
              onClick={() => onNavigate({ name: 'projects' })}
            >
              返回
            </button>
          </div>
        }
      />

      {error ? <InlineError message={error} onRetry={() => void load()} /> : null}

      <div className="stat-row">
        <StatTile label="任务总数" value={project.stats.totalTasks} />
        <StatTile label="已完成" value={project.stats.completedTasks} tone="green" />
        <StatTile label="待完成" value={project.stats.pendingTasks} />
        <StatTile
          label="逾期"
          value={overdue}
          tone={overdue > 0 ? 'red' : 'green'}
        />
      </div>

      <SectionCard
        no="01 /"
        title="整体进度"
        subtitle={`${project.stats.completionRate}% · 统计基于真实子任务`}
      >
        <ProgressBar
          percent={project.stats.completionRate}
          label={`${project.name} 完成率`}
          tone={overdue > 0 ? 'amber' : 'green'}
        />
        <dl className="project-facts">
          <div>
            <dt>开始日期</dt>
            <dd>{project.startDate ?? '未设置'}</dd>
          </div>
          <div>
            <dt>截止日期</dt>
            <dd>{project.dueDate ?? '未设置'}</dd>
          </div>
          <div>
            <dt>状态</dt>
            <dd>{PROJECT_STATUS_LABELS[project.status]}</dd>
          </div>
          <div>
            <dt>更新时间</dt>
            <dd>{new Date(project.updatedAt).toLocaleString('zh-CN')}</dd>
          </div>
        </dl>
      </SectionCard>

      <div className="main-grid project-detail-grid">
        <SectionCard
          no="02 /"
          title="项目任务"
          subtitle={`${tasks.length} 个顶层任务`}
          actions={
            <button
              className="paper-inline-button"
              type="button"
              onClick={() => {
                setEditingTask(null)
                setTaskModalOpen(true)
              }}
            >
              ＋ 新任务
            </button>
          }
        >
          <TaskList
            tasks={tasks}
            busyTaskId={busyTaskId}
            projects={projects}
            emptyContent={
              <EmptyState
                title="项目里还没有任务"
                description="先加一个任务，进度就会开始走动。"
                action={
                  <button
                    className="empty-action"
                    type="button"
                    onClick={() => {
                      setEditingTask(null)
                      setTaskModalOpen(true)
                    }}
                  >
                    ＋ 添加任务
                  </button>
                }
              />
            }
            onToggle={(task) => void toggleTask(task)}
            onEdit={(task) => {
              setEditingTask(task)
              setTaskModalOpen(true)
            }}
            onDelete={(task) => void deleteTask(task)}
          />
        </SectionCard>

        <SectionCard no="03 /" title="最近活动" subtitle="纪录来自真实数据库操作">
          <ActivityList activities={recentActivities} emptyText="还没有活动记录。" />
        </SectionCard>
      </div>

      <ProjectFormModal
        open={projectModalOpen}
        project={project}
        onCancel={() => setProjectModalOpen(false)}
        onSubmit={submitProject}
      />

      <TaskFormModal
        open={taskModalOpen}
        task={editingTask}
        projects={projects}
        defaultProjectId={project.id}
        onCancel={() => {
          setTaskModalOpen(false)
          setEditingTask(null)
        }}
        onSubmit={submitTask}
      />
    </div>
  )
}
