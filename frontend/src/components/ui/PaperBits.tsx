import type { ReactNode } from 'react'
import {
  PRIORITY_LABELS,
  PROJECT_STATUS_LABELS,
  type ProjectStatus,
  type TaskPriority,
} from '../../types'

export function PriorityTag({
  priority,
  subtle = false,
}: {
  priority: TaskPriority
  subtle?: boolean
}) {
  return (
    <span className={`priority-tag priority-${priority} ${subtle ? 'is-subtle' : ''}`}>
      <span aria-hidden="true">●</span>
      {PRIORITY_LABELS[priority]}
    </span>
  )
}

export function ProjectChip({
  name,
  status,
  onClick,
}: {
  name: string
  status?: ProjectStatus
  onClick?: () => void
}) {
  const content = (
    <>
      <span aria-hidden="true">▤</span>
      {name}
      {status ? <em>{PROJECT_STATUS_LABELS[status]}</em> : null}
    </>
  )
  if (onClick) {
    return (
      <button className="project-chip" type="button" onClick={onClick}>
        {content}
      </button>
    )
  }
  return <span className="project-chip">{content}</span>
}

export function ProgressBar({
  percent,
  label,
  tone = 'ink',
}: {
  percent: number
  label?: string
  tone?: 'ink' | 'green' | 'amber'
}) {
  const clamped = Math.max(0, Math.min(100, Math.round(percent)))
  return (
    <div className={`progress-track progress-${tone}`}>
      <div
        className="progress-fill"
        style={{ width: `${clamped}%` }}
        role="progressbar"
        aria-valuenow={clamped}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label ?? '完成进度'}
      />
      <span className="progress-label">{clamped}%</span>
    </div>
  )
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string
  description?: string
  action?: ReactNode
}) {
  return (
    <div className="empty-note empty-note-small">
      <p className="empty-title">{title}</p>
      {description ? <p className="empty-sub">{description}</p> : null}
      {action}
    </div>
  )
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow: string
  title: ReactNode
  description?: string
  actions?: ReactNode
}) {
  return (
    <section className="paper-hero page-hero">
      <div className="hero-copy">
        <p className="eyebrow">
          <i aria-hidden="true" />
          {eyebrow}
        </p>
        <h1>{title}</h1>
        {description ? <p className="hero-sub">{description}</p> : null}
      </div>
      {actions ? <div className="hero-actions">{actions}</div> : null}
    </section>
  )
}

export function SectionCard({
  no,
  title,
  subtitle,
  actions,
  children,
  tone = 'sheet',
}: {
  no: string
  title: string
  subtitle?: string
  actions?: ReactNode
  children: ReactNode
  tone?: 'sheet' | 'sticky'
}) {
  return (
    <section className={`task-sheet section-card ${tone === 'sticky' ? 'is-sticky' : ''}`}>
      <div className={tone === 'sticky' ? 'assistant-tape' : 'sheet-tape'} aria-hidden="true" />
      <header className="sheet-head">
        <div className="sheet-heading">
          <span className="section-no">{no}</span>
          <div>
            <h2>{title}</h2>
            {subtitle ? <p className="sheet-subtitle">{subtitle}</p> : null}
          </div>
        </div>
        {actions ? <div className="sheet-tools">{actions}</div> : null}
      </header>
      <div className="sheet-rule" aria-hidden="true" />
      {children}
    </section>
  )
}

export function StatTile({
  label,
  value,
  hint,
  tone,
}: {
  label: string
  value: number | string
  hint?: string
  tone?: 'ink' | 'green' | 'amber' | 'red'
}) {
  return (
    <div className={`stat-tile ${tone ? `tone-${tone}` : ''}`}>
      <strong>{typeof value === 'number' ? String(value).padStart(2, '0') : value}</strong>
      <span>{label}</span>
      {hint ? <em>{hint}</em> : null}
    </div>
  )
}

export function InlineError({
  message,
  onRetry,
}: {
  message: string
  onRetry?: () => void
}) {
  return (
    <div className="inline-error" role="alert">
      <span>{message}</span>
      {onRetry ? (
        <button className="paper-inline-button" type="button" onClick={onRetry}>
          重新加载
        </button>
      ) : null}
    </div>
  )
}
