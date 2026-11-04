import { useState, type CSSProperties } from 'react'
import {
  PROJECT_STATUS_LABELS,
  type Project,
} from '../types'
import { isFreshlyPasted, noteTilt } from '../utils/motion'
import { NoteTape, NoteTearBurst } from './ui/NotePaper'
import { ProgressBar } from './ui/PaperBits'

interface ProjectNoteProps {
  project: Project
  tearing?: boolean
  landing?: boolean
  onOpen: () => void
  onEdit: () => void
  onTear: () => void
}

/** A project is a bigger index card taped to the wall; archiving tears it off. */
export function ProjectNote({
  project,
  tearing = false,
  landing = false,
  onOpen,
  onEdit,
  onTear,
}: ProjectNoteProps) {
  const [pasting] = useState(() => isFreshlyPasted(project.createdAt))
  const archived = project.status === 'archived'
  const classes = [
    'project-card',
    'project-note',
    archived ? 'is-torn' : '',
    pasting ? 'is-pasting' : '',
    tearing ? 'is-tearing' : '',
    landing ? 'is-landing' : '',
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <article
      className={classes}
      style={{ '--tilt': `${noteTilt(project.id) * 0.6}deg` } as CSSProperties}
      data-testid="project-note"
    >
      <span className="note-paper" aria-hidden="true" />
      <NoteTape peeled={archived} />

      <div className="project-note-body">
        <div className="project-card-top">
          <button className="project-card-title" type="button" onClick={onOpen}>
            {project.name}
          </button>
          <span className={`project-status status-${project.status}`}>
            {PROJECT_STATUS_LABELS[project.status]}
          </span>
        </div>
        {project.description ? (
          <p className="project-card-description">{project.description}</p>
        ) : (
          <p className="project-card-description muted">还没有描述</p>
        )}
        <div className="project-card-dates">
          <span>开始 {project.startDate ?? '未设置'}</span>
          <span>截止 {project.dueDate ?? '未设置'}</span>
        </div>
        <ProgressBar
          percent={project.stats.completionRate}
          label={`${project.name} 完成率`}
          tone={project.stats.overdueTasks > 0 ? 'amber' : 'green'}
        />
        <div className="project-card-stats">
          <span>
            <strong>{project.stats.completedTasks}</strong>/{project.stats.totalTasks} 完成
          </span>
          <span>待完成 {project.stats.pendingTasks}</span>
          <span className={project.stats.overdueTasks > 0 ? 'is-overdue' : ''}>
            逾期 {project.stats.overdueTasks}
          </span>
        </div>
        <div className="project-card-actions">
          <button className="paper-inline-button" type="button" onClick={onOpen}>
            查看
          </button>
          <button className="paper-inline-button" type="button" onClick={onEdit}>
            编辑
          </button>
          <button
            className="paper-inline-button"
            type="button"
            disabled={tearing}
            aria-label={archived ? `贴回去项目「${project.name}」` : `撕下归档项目「${project.name}」`}
            onClick={onTear}
          >
            {archived ? '贴回去' : '撕下归档'}
          </button>
        </div>
      </div>

      {tearing ? <NoteTearBurst /> : null}
    </article>
  )
}
