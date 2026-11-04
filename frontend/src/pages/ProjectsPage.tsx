import { App, Spin } from 'antd'
import { useState } from 'react'
import { ProjectFormModal } from '../components/ProjectFormModal'
import { ProjectNote } from '../components/ProjectNote'
import {
  EmptyState,
  InlineError,
  PageHeader,
  SectionCard,
} from '../components/ui/PaperBits'
import { useNoteTear } from '../hooks/useNoteTear'
import { useProjects } from '../hooks/useProjects'
import { getApiErrorMessage } from '../services/http'
import {
  type AppRoute,
  type Project,
  type ProjectInput,
  type ProjectStatus,
} from '../types'

const STATUS_FILTERS: Array<{ label: string; value: ProjectStatus | 'all' }> = [
  { label: '全部状态', value: 'all' },
  { label: '规划中', value: 'planning' },
  { label: '进行中', value: 'active' },
  { label: '已完成', value: 'completed' },
  { label: '已归档', value: 'archived' },
]

interface ProjectsPageProps {
  dataVersion: number
  onDataChanged: () => void
  onNavigate: (route: AppRoute) => void
}

export function ProjectsPage({
  dataVersion,
  onDataChanged,
  onNavigate,
}: ProjectsPageProps) {
  void dataVersion
  const { message } = App.useApp()
  const [statusFilter, setStatusFilter] = useState<ProjectStatus | 'all'>('all')
  const {
    projects,
    loading,
    error,
    reload,
    createProject,
    editProject,
    archiveProject,
    restoreProject,
  } = useProjects({
    status: statusFilter === 'all' ? undefined : statusFilter,
    includeArchived: true,
  })
  const [modalOpen, setModalOpen] = useState(false)
  const [editingProject, setEditingProject] = useState<Project | null>(null)

  const { tearing, landingId, tear } = useNoteTear(async (project: Project) => {
    try {
      if (project.status === 'archived') {
        await restoreProject(project.id)
        message.success('又贴回墙上了。')
      } else {
        await archiveProject(project.id)
        message.success('撕下来了，历史任务与活动都留在归档里。')
      }
      onDataChanged()
    } catch (archiveError) {
      message.error(getApiErrorMessage(archiveError))
      throw archiveError
    }
  })

  const openCreate = () => {
    setEditingProject(null)
    setModalOpen(true)
  }

  const openEdit = (project: Project) => {
    setEditingProject(project)
    setModalOpen(true)
  }

  const handleSubmit = async (input: ProjectInput) => {
    if (editingProject) {
      await editProject(editingProject.id, input)
      message.success('项目已更新。')
    } else {
      await createProject(input)
      message.success('贴上一张新的项目卡。')
    }
    setModalOpen(false)
    setEditingProject(null)
    onDataChanged()
  }

  const summary = projects.reduce(
    (total, project) => {
      total.total += project.stats.totalTasks
      total.completed += project.stats.completedTasks
      return total
    },
    { total: 0, completed: 0 },
  )

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="PROJECTS / 一件长一点的事"
        title={
          <>
            把一段路，
            <br />
            <span className="marker">切成看得见的进度。</span>
          </>
        }
        description={
          projects.length > 0
            ? `${projects.length} 张项目卡，共 ${summary.total} 个任务，已完成 ${summary.completed} 个。做完就撕下来收进归档。`
            : '还没有项目。为一个长期目标贴一张卡，让进度有地方落脚。'
        }
        actions={
          <button className="paper-inline-button primary" type="button" onClick={openCreate}>
            <span aria-hidden="true">＋</span> 新建项目
          </button>
        }
      />

      {error ? <InlineError message={error} onRetry={() => void reload()} /> : null}

      <div className="filter-row project-filters">
        <label className="sort-control">
          <span className="sort-prefix">状态</span>
          <select
            aria-label="按项目状态筛选"
            value={statusFilter}
            onChange={(event) =>
              setStatusFilter(event.target.value as ProjectStatus | 'all')
            }
          >
            {STATUS_FILTERS.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <span className="muted-note">归档项目保留全部历史任务与活动记录。</span>
      </div>

      {loading && projects.length === 0 ? (
        <div className="center-state">
          <Spin size="large" />
          <p>正在整理项目夹…</p>
        </div>
      ) : null}

      {!loading && projects.length === 0 ? (
        <SectionCard no="01 /" title="项目墙" subtitle="目前是空的">
          <EmptyState
            title="还没有项目"
            description="例如：两周内完成一个 AI Agent 项目。"
            action={
              <button className="empty-action" type="button" onClick={openCreate}>
                <span aria-hidden="true">＋</span> 创建第一个项目
              </button>
            }
          />
        </SectionCard>
      ) : (
        <div className="project-grid">
          {projects.map((project, index) => (
            <ProjectNote
              key={project.id}
              project={project}
              tearing={tearing?.item.id === project.id}
              landing={landingId === project.id}
              onOpen={() => onNavigate({ name: 'project', id: project.id })}
              onEdit={() => openEdit(project)}
              onTear={() => void tear(project, index)}
            />
          ))}
        </div>
      )}

      <ProjectFormModal
        open={modalOpen}
        project={editingProject}
        onCancel={() => {
          setModalOpen(false)
          setEditingProject(null)
        }}
        onSubmit={handleSubmit}
      />
    </div>
  )
}
