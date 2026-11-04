import { DatePicker, Input, InputNumber, Select } from 'antd'
import { useMemo, useState } from 'react'
import type {
  BreakdownDraft,
  BreakdownSubtaskDraft,
  BreakdownTaskDraft,
  PlanDraft,
  Project,
  ReportDraft,
  TaskPriority,
} from '../types'
import { formatDateTime, toAppTimezone, toIsoString } from '../utils/datetime'

const PRIORITY_OPTIONS: Array<{ label: string; value: TaskPriority }> = [
  { label: '高', value: 'high' },
  { label: '中', value: 'medium' },
  { label: '弱', value: 'low' },
]

const MAX_TASKS = 12
const MAX_SUBTASKS = 8

function emptySubtask(): BreakdownSubtaskDraft {
  return {
    title: '',
    description: null,
    priority: 'medium',
    estimatedMinutes: null,
    dueAt: null,
  }
}

function emptyTask(): BreakdownTaskDraft {
  return {
    title: '',
    description: null,
    priority: 'medium',
    estimatedMinutes: null,
    dueAt: null,
    subtasks: [],
  }
}

function totalMinutes(draft: BreakdownDraft): number {
  return draft.tasks.reduce((total, task) => {
    const own = task.estimatedMinutes ?? 0
    const children = task.subtasks.reduce(
      (sum, subtask) => sum + (subtask.estimatedMinutes ?? 0),
      0,
    )
    return total + own + children
  }, 0)
}

interface BreakdownTaskRowProps {
  task: BreakdownTaskDraft
  index: number
  disabled: boolean
  onChange: (task: BreakdownTaskDraft) => void
  onRemove: () => void
}

function BreakdownTaskRow({
  task,
  index,
  disabled,
  onChange,
  onRemove,
}: BreakdownTaskRowProps) {
  const [newSubtask, setNewSubtask] = useState('')

  const update = (patch: Partial<BreakdownTaskDraft>) => onChange({ ...task, ...patch })
  const updateSubtask = (subIndex: number, patch: Partial<BreakdownSubtaskDraft>) => {
    const subtasks = task.subtasks.map((subtask, current) =>
      current === subIndex ? { ...subtask, ...patch } : subtask,
    )
    update({ subtasks })
  }

  const addSubtask = () => {
    const title = newSubtask.trim()
    if (!title || task.subtasks.length >= MAX_SUBTASKS) {
      return
    }
    update({ subtasks: [...task.subtasks, { ...emptySubtask(), title }] })
    setNewSubtask('')
  }

  return (
    <li className="breakdown-task">
      <div className="breakdown-task-head">
        <span className="breakdown-order">{String(index + 1).padStart(2, '0')}</span>
        <Input
          value={task.title}
          disabled={disabled}
          maxLength={100}
          placeholder="任务标题"
          aria-label={`拆解任务 ${index + 1} 标题`}
          onChange={(event) => update({ title: event.target.value })}
        />
        <Select
          value={task.priority}
          disabled={disabled}
          options={PRIORITY_OPTIONS}
          style={{ width: 78 }}
          aria-label={`拆解任务 ${index + 1} 优先级`}
          onChange={(value: TaskPriority) => update({ priority: value })}
        />
        <InputNumber
          value={task.estimatedMinutes}
          disabled={disabled}
          min={5}
          max={1440}
          step={5}
          placeholder="分钟"
          style={{ width: 96 }}
          aria-label={`拆解任务 ${index + 1} 预计耗时`}
          onChange={(value) => update({ estimatedMinutes: value ?? null })}
        />
        <DatePicker
          value={task.dueAt ? toAppTimezone(task.dueAt) : null}
          disabled={disabled}
          showTime={{ format: 'HH:mm' }}
          format="MM-DD HH:mm"
          placeholder="截止"
          style={{ width: 138 }}
          aria-label={`拆解任务 ${index + 1} 截止时间`}
          onChange={(value) => update({ dueAt: toIsoString(value) })}
        />
        <button
          className="task-action danger"
          type="button"
          disabled={disabled}
          aria-label={`删除拆解任务 ${task.title || index + 1}`}
          onClick={onRemove}
        >
          删除
        </button>
      </div>

      <div className="breakdown-subtasks">
        {task.subtasks.map((subtask, subIndex) => (
          <div className="breakdown-subtask" key={`${index}-${subIndex}`}>
            <span aria-hidden="true">⤷</span>
            <Input
              value={subtask.title}
              disabled={disabled}
              maxLength={100}
              placeholder="子任务标题"
              aria-label={`拆解任务 ${index + 1} 子任务 ${subIndex + 1} 标题`}
              onChange={(event) =>
                updateSubtask(subIndex, { title: event.target.value })
              }
            />
            <InputNumber
              value={subtask.estimatedMinutes}
              disabled={disabled}
              min={5}
              max={1440}
              step={5}
              placeholder="分钟"
              style={{ width: 92 }}
              aria-label={`拆解任务 ${index + 1} 子任务 ${subIndex + 1} 预计耗时`}
              onChange={(value) =>
                updateSubtask(subIndex, { estimatedMinutes: value ?? null })
              }
            />
            <button
              className="task-action danger"
              type="button"
              disabled={disabled}
              aria-label={`删除拆解子任务 ${subtask.title || subIndex + 1}`}
              onClick={() =>
                update({
                  subtasks: task.subtasks.filter((_, current) => current !== subIndex),
                })
              }
            >
              删除
            </button>
          </div>
        ))}
        {task.subtasks.length < MAX_SUBTASKS ? (
          <div className="breakdown-subtask-add">
            <Input
              value={newSubtask}
              disabled={disabled}
              maxLength={100}
              placeholder="添加子任务…"
              aria-label={`为拆解任务 ${index + 1} 添加子任务`}
              onChange={(event) => setNewSubtask(event.target.value)}
              onPressEnter={addSubtask}
            />
            <button
              className="paper-inline-button"
              type="button"
              disabled={disabled || !newSubtask.trim()}
              onClick={addSubtask}
            >
              添加
            </button>
          </div>
        ) : null}
      </div>
    </li>
  )
}

interface BreakdownEditorProps {
  breakdown: BreakdownDraft
  projects: Project[]
  busy: boolean
  onConfirm: (draft: BreakdownDraft) => void
  onCancel: () => void
}

export function BreakdownEditor({
  breakdown,
  projects,
  busy,
  onConfirm,
  onCancel,
}: BreakdownEditorProps) {
  const [draft, setDraft] = useState<BreakdownDraft>(breakdown)
  const invalid = useMemo(
    () =>
      draft.tasks.length === 0 ||
      draft.tasks.some(
        (task) =>
          !task.title.trim() ||
          task.subtasks.some((subtask) => !subtask.title.trim()),
      ),
    [draft],
  )
  const minutes = totalMinutes(draft)
  const project = projects.find((item) => item.id === draft.projectId)

  return (
    <div className="breakdown-editor">
      <div className="breakdown-head">
        <label className="breakdown-field">
          <span>目标</span>
          <Input
            value={draft.goal}
            maxLength={200}
            disabled={busy}
            aria-label="任务拆解目标"
            onChange={(event) => setDraft({ ...draft, goal: event.target.value })}
          />
        </label>
        <label className="breakdown-field">
          <span>所属项目</span>
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            value={draft.projectId}
            disabled={busy}
            placeholder="不归属项目"
            aria-label="任务拆解所属项目"
            options={projects.map((item) => ({
              label: item.name,
              value: item.id,
            }))}
            onChange={(value: string | undefined) =>
              setDraft({ ...draft, projectId: value ?? null })
            }
          />
        </label>
      </div>

      {project?.dueDate ? (
        <p className="muted-note">项目截止日期：{project.dueDate}</p>
      ) : null}

      <ol className="breakdown-tasks">
        {draft.tasks.map((task, index) => (
          <BreakdownTaskRow
            key={index}
            task={task}
            index={index}
            disabled={busy}
            onChange={(next) =>
              setDraft({
                ...draft,
                tasks: draft.tasks.map((item, current) =>
                  current === index ? next : item,
                ),
              })
            }
            onRemove={() =>
              setDraft({
                ...draft,
                tasks: draft.tasks.filter((_, current) => current !== index),
              })
            }
          />
        ))}
      </ol>

      <div className="breakdown-footer">
        <span>
          共 {draft.tasks.length} 组任务 · 预计 {minutes} 分钟
        </span>
        <button
          className="paper-inline-button"
          type="button"
          disabled={busy || draft.tasks.length >= MAX_TASKS}
          onClick={() => setDraft({ ...draft, tasks: [...draft.tasks, emptyTask()] })}
        >
          ＋ 添加任务
        </button>
      </div>

      {invalid ? (
        <p className="muted-note warn">请补全所有任务与子任务的标题后再确认。</p>
      ) : null}

      <div className="action-actions">
        <button
          className="paper-inline-button primary"
          type="button"
          disabled={busy || invalid}
          onClick={() => onConfirm(draft)}
        >
          {busy ? '正在创建…' : '确认并创建'}
        </button>
        <button
          className="paper-inline-button"
          type="button"
          disabled={busy}
          onClick={onCancel}
        >
          取消操作
        </button>
      </div>
      <p className="action-result-note">确认后才会写入任务；未确认前不会创建任何数据。</p>
    </div>
  )
}

interface PlanDraftCardProps {
  plan: PlanDraft
  busy: boolean
  onConfirm: (plan: PlanDraft) => void
  onCancel: () => void
}

export function PlanDraftCard({ plan, busy, onConfirm, onCancel }: PlanDraftCardProps) {
  const [items, setItems] = useState(plan.items)
  const total = Math.round(
    items.reduce(
      (sum, item) =>
        sum + (new Date(item.endAt).getTime() - new Date(item.startAt).getTime()) / 60000,
      0,
    ),
  )

  return (
    <div className="plan-draft-card">
      <div className="plan-draft-head">
        <strong>{plan.planDate} 的今日计划</strong>
        <span>
          可用 {plan.availableMinutes} 分钟 · 已排 {total} 分钟
        </span>
      </div>
      {items.length === 0 ? (
        <p className="muted-note">计划里还没有时间块。</p>
      ) : (
        <ul className="plan-draft-items">
          {items.map((item) => (
            <li key={`${item.taskId}-${item.startAt}`}>
              <span className="plan-time">
                {toAppTimezone(item.startAt).format('HH:mm')}–
                {toAppTimezone(item.endAt).format('HH:mm')}
              </span>
              <span className="plan-title">
                {item.taskTitle ?? '任务'} {item.note ? `· ${item.note}` : ''}
              </span>
              <button
                className="task-action danger"
                type="button"
                disabled={busy}
                aria-label={`移除计划时间块 ${item.startAt}`}
                onClick={() =>
                  setItems(items.filter((current) => current !== item))
                }
              >
                移除
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="action-actions">
        <button
          className="paper-inline-button primary"
          type="button"
          disabled={busy}
          onClick={() => onConfirm({ ...plan, items })}
        >
          {busy ? '正在保存…' : '确认保存计划'}
        </button>
        <button
          className="paper-inline-button"
          type="button"
          disabled={busy}
          onClick={onCancel}
        >
          取消操作
        </button>
      </div>
      <p className="action-result-note">确认后才会保存今日计划；未确认不会写入。</p>
    </div>
  )
}

interface ReportDraftCardProps {
  report: ReportDraft
  busy: boolean
  onConfirm: () => void
  onCancel: () => void
  onPreview?: () => void
}

export function ReportDraftCard({
  report,
  busy,
  onConfirm,
  onCancel,
  onPreview,
}: ReportDraftCardProps) {
  return (
    <div className="report-draft-card">
      <div className="report-draft-head">
        <strong>{report.title}</strong>
        <span>
          {formatDateTime(report.periodStart)} 至 {formatDateTime(report.periodEnd)}
          {report.aiUsed ? ' · 含 AI 建议' : ' · 仅后端统计'}
        </span>
      </div>
      <pre className="report-draft-preview">{report.contentMd.slice(0, 900)}</pre>
      <div className="action-actions">
        <button
          className="paper-inline-button primary"
          type="button"
          disabled={busy}
          onClick={onConfirm}
        >
          {busy ? '正在保存…' : '确认保存报告'}
        </button>
        {onPreview ? (
          <button className="paper-inline-button" type="button" onClick={onPreview}>
            查看完整内容
          </button>
        ) : null}
        <button
          className="paper-inline-button"
          type="button"
          disabled={busy}
          onClick={onCancel}
        >
          取消操作
        </button>
      </div>
      <p className="action-result-note">
        统计由后端计算；确认后才保存，未确认不会写入报告。
      </p>
    </div>
  )
}
