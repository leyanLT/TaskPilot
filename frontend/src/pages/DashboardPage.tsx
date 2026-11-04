import { Spin } from 'antd'
import { ActivityList } from '../components/ActivityList'
import { InsightBoard } from '../components/InsightBoard'
import { PlanTimeline } from '../components/PlanTimeline'
import {
  EmptyState,
  InlineError,
  PageHeader,
  PriorityTag,
  ProgressBar,
  SectionCard,
  StatTile,
} from '../components/ui/PaperBits'
import { useDashboard } from '../hooks/useDashboard'
import { taskApi } from '../services/tasks'
import type { AppRoute, Project, Task } from '../types'
import { formatDueLabel, isTaskOverdue } from '../utils/datetime'

interface DashboardPageProps {
  dataVersion: number
  onOpenTask: (taskId: string) => void
  onNavigate: (route: AppRoute) => void
}

function CompactTaskList({
  tasks,
  projects,
  emptyText,
  onOpenTask,
  onToggle,
}: {
  tasks: Task[]
  projects: Project[]
  emptyText: string
  onOpenTask: (taskId: string) => void
  onToggle: (task: Task) => void
}) {
  if (tasks.length === 0) {
    return <p className="muted-note">{emptyText}</p>
  }
  return (
    <ul className="compact-task-list">
      {tasks.map((task) => {
        const project = task.projectId
          ? projects.find((item) => item.id === task.projectId)
          : null
        return (
          <li key={task.id} className={isTaskOverdue(task) ? 'is-overdue' : ''}>
            <button
              className="compact-check"
              type="button"
              aria-label={`完成任务 ${task.title}`}
              onClick={() => onToggle(task)}
            >
              ○
            </button>
            <button
              className="compact-task-main"
              type="button"
              onClick={() => onOpenTask(task.id)}
            >
              <span className="compact-title">{task.title}</span>
              <PriorityTag priority={task.priority} subtle />
              {project ? <span className="compact-project">{project.name}</span> : null}
            </button>
            <span className="compact-due">{formatDueLabel(task.dueAt)}</span>
          </li>
        )
      })}
    </ul>
  )
}

function ProjectOverviewCard({
  project,
  onOpen,
}: {
  project: Project
  onOpen: () => void
}) {
  return (
    <button className="project-card is-compact" type="button" onClick={onOpen}>
      <span className="project-card-top">
        <strong>{project.name}</strong>
        <span className={`project-status status-${project.status}`}>
          {project.stats.completionRate}%
        </span>
      </span>
      <ProgressBar percent={project.stats.completionRate} label={`${project.name} 完成率`} />
      <span className="project-card-meta">
        待完成 {project.stats.pendingTasks} · 逾期 {project.stats.overdueTasks}
        {project.dueDate ? ` · 截止 ${project.dueDate}` : ''}
      </span>
    </button>
  )
}

export function DashboardPage({
  dataVersion,
  onOpenTask,
  onNavigate,
}: DashboardPageProps) {
  const { dashboard, loading, error, reload } = useDashboard(dataVersion)

  const toggleTask = async (task: Task) => {
    await taskApi.update(task.id, { status: 'completed' })
    await reload()
  }

  if (loading && !dashboard) {
    return (
      <div className="center-state page-state" aria-label="看板加载中">
        <Spin size="large" />
        <p>正在整理今天的纸页…</p>
      </div>
    )
  }

  if (error && !dashboard) {
    return (
      <div className="page-state">
        <InlineError message={error} onRetry={() => void reload()} />
      </div>
    )
  }

  const data = dashboard
  const counts = data?.counts
  const pendingLine =
    counts && counts.pending > 0
      ? `还有 ${counts.pending} 件小事。先挑一件开始。`
      : '今天没有待办了，给自己留一点空白。'

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="TODAY, SLOWLY / 今天慢慢来"
        title={
          <>
            把今天，
            <br />
            <span className="marker">做轻一点。</span>
          </>
        }
        description={pendingLine}
        actions={
          <div className="hero-actions-row">
            <button
              className="paper-inline-button primary"
              type="button"
              onClick={() => onNavigate({ name: 'today' })}
            >
              安排今天
            </button>
            <button
              className="paper-inline-button"
              type="button"
              onClick={() => onNavigate({ name: 'assistant' })}
            >
              问问小帮手
            </button>
          </div>
        }
      />

      {error ? <InlineError message={error} onRetry={() => void reload()} /> : null}

      <div className="stat-row">
        <StatTile label="任务总数" value={counts?.total ?? 0} />
        <StatTile label="待完成" value={counts?.pending ?? 0} tone="ink" />
        <StatTile label="已完成" value={counts?.completed ?? 0} tone="green" />
        <StatTile
          label="逾期"
          value={counts?.overdue ?? 0}
          tone={counts && counts.overdue > 0 ? 'red' : 'green'}
        />
      </div>

      <div className="dashboard-grid">
        <SectionCard
          no="01 /"
          title="今日任务"
          subtitle={`${counts?.dueToday ?? 0} 件今天到期 · ${counts?.dueSoon ?? 0} 件 24 小时内到期`}
          actions={
            <a className="sheet-link" href="#/tasks">
              全部任务 →
            </a>
          }
        >
          <CompactTaskList
            tasks={data?.todayTasks ?? []}
            projects={data?.projects ?? []}
            emptyText="今天没有到期的任务，可以从待办里挑一件。"
            onOpenTask={onOpenTask}
            onToggle={(task) => void toggleTask(task)}
          />
          {(data?.dueSoonTasks.length ?? 0) > 0 ? (
            <div className="dashboard-subsection">
              <h3>即将截止</h3>
              <CompactTaskList
                tasks={data?.dueSoonTasks ?? []}
                projects={data?.projects ?? []}
                emptyText=""
                onOpenTask={onOpenTask}
                onToggle={(task) => void toggleTask(task)}
              />
            </div>
          ) : null}
        </SectionCard>

        <SectionCard
          no="02 /"
          title="今日计划"
          subtitle={
            data?.todayPlan
              ? `已安排 ${data.todayPlan.plannedMinutes} / ${data.todayPlan.availableMinutes} 分钟`
              : '还没有安排今天的时间块'
          }
          actions={
            <a className="sheet-link" href="#/today">
              去安排 →
            </a>
          }
        >
          <PlanTimeline
            plan={data?.todayPlan ?? null}
            emptyText="还没有今日计划，去「今日」页排一个时间块。"
          />
        </SectionCard>

        <SectionCard
          no="03 /"
          title="项目进度"
          subtitle={`${data?.projects.length ?? 0} 个进行中的项目`}
          actions={
            <a className="sheet-link" href="#/projects">
              全部项目 →
            </a>
          }
        >
          {(data?.projects.length ?? 0) === 0 ? (
            <EmptyState
              title="还没有项目"
              description="给一段时间的事建一个项目，进度会自己长出来。"
              action={
                <a className="empty-action" href="#/projects">
                  去创建项目
                </a>
              }
            />
          ) : (
            <div className="project-mini-grid">
              {(data?.projects ?? []).map((project) => (
                <ProjectOverviewCard
                  key={project.id}
                  project={project}
                  onOpen={() => onNavigate({ name: 'project', id: project.id })}
                />
              ))}
            </div>
          )}
        </SectionCard>

        <SectionCard no="04 /" title="最近活动" subtitle="来自真实任务与项目记录">
          <ActivityList
            activities={data?.recentActivities ?? []}
            emptyText="还没有活动记录。"
          />
        </SectionCard>

        <SectionCard
          no="05 /"
          title="需要留意"
          subtitle="按真实截止时间、依赖与专注记录计算"
        >
          <InsightBoard dataVersion={dataVersion} onOpenTask={onOpenTask} />
        </SectionCard>
      </div>

      <div className="dashboard-hint">
        <span aria-hidden="true">✎</span>
        小提示：先在「今日」排出时间块，再让 AI 帮你拆解大目标，进度会慢慢连成线。
      </div>
    </div>
  )
}
