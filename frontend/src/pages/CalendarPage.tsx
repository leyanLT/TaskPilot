/* oxlint-disable react/set-state-in-effect -- data loading on mount; state is set after the request resolves. */
import { App, Modal, Spin } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  InlineError,
  PageHeader,
  SectionCard,
} from '../components/ui/PaperBits'
import { getApiErrorMessage } from '../services/http'
import { calendarApi, replanApi } from '../services/v2'
import { taskApi } from '../services/tasks'
import type { Project, Task } from '../types'
import type { CalendarDay, CalendarRange, ReplanDraft, TimeBlock } from '../types/v2'
import {
  combineLocalDateTime,
  formatDueLabel,
  toAppTimezone,
  toIsoString,
  todayLocalDate,
} from '../utils/datetime'

type CalendarView = 'month' | 'week' | 'day'

const WEEK_HEADERS = ['一', '二', '三', '四', '五', '六', '日']

function mondayOf(date: string): Dayjs {
  const value = dayjs(date)
  const offset = (value.day() + 6) % 7
  return value.subtract(offset, 'day')
}

function rangeFor(view: CalendarView, cursor: string): { start: string; end: string } {
  const current = dayjs(cursor)
  if (view === 'day') {
    return { start: current.format('YYYY-MM-DD'), end: current.format('YYYY-MM-DD') }
  }
  if (view === 'week') {
    const start = mondayOf(cursor)
    return {
      start: start.format('YYYY-MM-DD'),
      end: start.add(6, 'day').format('YYYY-MM-DD'),
    }
  }
  const first = current.startOf('month')
  const gridStart = mondayOf(first.format('YYYY-MM-DD'))
  return {
    start: gridStart.format('YYYY-MM-DD'),
    end: gridStart.add(41, 'day').format('YYYY-MM-DD'),
  }
}

function minutesOf(block: TimeBlock): number {
  return Math.max(
    0,
    Math.round(dayjs(block.endAt).diff(dayjs(block.startAt), 'minute')),
  )
}

export function CalendarPage({
  projects,
  dataVersion,
  onDataChanged,
}: {
  projects: Project[]
  dataVersion: number
  onDataChanged: () => void
}) {
  const { message } = App.useApp()
  const [view, setView] = useState<CalendarView>('month')
  const [cursor, setCursor] = useState(todayLocalDate())
  const [selected, setSelected] = useState(todayLocalDate())
  const [projectFilter, setProjectFilter] = useState('all')
  const [data, setData] = useState<CalendarRange | null>(null)
  const [tasks, setTasks] = useState<Task[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [draft, setDraft] = useState<ReplanDraft | null>(null)
  const [busy, setBusy] = useState(false)
  const [newTaskId, setNewTaskId] = useState('')
  const [newStart, setNewStart] = useState('09:00')
  const [newEnd, setNewEnd] = useState('10:00')
  const [editingBlockId, setEditingBlockId] = useState<string | null>(null)
  const [editStart, setEditStart] = useState('09:00')
  const [editEnd, setEditEnd] = useState('10:00')

  const range = useMemo(() => rangeFor(view, cursor), [view, cursor])

  const load = useCallback(async () => {
    setError(null)
    try {
      const [calendar, pending] = await Promise.all([
        calendarApi.range(
          range.start,
          range.end,
          projectFilter === 'all' ? undefined : projectFilter,
        ),
        taskApi.list({ status: 'pending' }),
      ])
      setData(calendar)
      setTasks(pending)
      setNewTaskId((current) => current || pending[0]?.id || '')
    } catch (loadError) {
      setError(getApiErrorMessage(loadError))
    } finally {
      setLoading(false)
    }
  }, [range.start, range.end, projectFilter])

  useEffect(() => {
    void load()
  }, [load, dataVersion])

  const dayMap = useMemo(() => {
    const map = new Map<string, CalendarDay>()
    data?.days.forEach((day) => map.set(day.date, day))
    return map
  }, [data])

  const selectedDay = dayMap.get(selected) ?? null

  const selectDay = (date: string) => {
    setSelected(date)
    if (view === 'month') {
      setCursor(date)
    }
  }

  const shift = (direction: -1 | 1) => {
    const step = view === 'day' ? 1 : view === 'week' ? 7 : 30
    const next = dayjs(cursor).add(direction * step, 'day').format('YYYY-MM-DD')
    setCursor(next)
    setSelected(next)
  }

  const reload = async () => {
    await load()
    onDataChanged()
  }

  const createBlock = async () => {
    if (!newTaskId) {
      message.warning('先选一个任务。')
      return
    }
    setBusy(true)
    try {
      await calendarApi.createBlock({
        planDate: selected,
        taskId: newTaskId,
        startAt: toIsoString(combineLocalDateTime(selected, newStart)) ?? '',
        endAt: toIsoString(combineLocalDateTime(selected, newEnd)) ?? '',
      })
      message.success('时间块已安排。')
      await reload()
    } catch (createError) {
      message.error(getApiErrorMessage(createError))
    } finally {
      setBusy(false)
    }
  }

  const removeBlock = async (block: TimeBlock) => {
    setBusy(true)
    try {
      await calendarApi.deleteBlock(block.id)
      message.success('时间块已取消。')
      await reload()
    } catch (deleteError) {
      message.error(getApiErrorMessage(deleteError))
    } finally {
      setBusy(false)
    }
  }

  const beginEdit = (block: TimeBlock) => {
    setEditingBlockId(block.id)
    setEditStart(toAppTimezone(block.startAt).format('HH:mm'))
    setEditEnd(toAppTimezone(block.endAt).format('HH:mm'))
  }

  const saveEdit = async (block: TimeBlock) => {
    setBusy(true)
    try {
      await calendarApi.updateBlock(block.id, {
        startAt: toIsoString(combineLocalDateTime(selected, editStart)) ?? '',
        endAt: toIsoString(combineLocalDateTime(selected, editEnd)) ?? '',
      })
      message.success('时间块已调整。')
      setEditingBlockId(null)
      await reload()
    } catch (updateError) {
      message.error(getApiErrorMessage(updateError))
    } finally {
      setBusy(false)
    }
  }

  const previewReplan = async () => {
    setBusy(true)
    try {
      const result = await replanApi.preview(selected, '在日历里重新安排这一天')
      setDraft(result)
    } catch (previewError) {
      message.error(getApiErrorMessage(previewError))
    } finally {
      setBusy(false)
    }
  }

  const applyReplan = async () => {
    if (!draft) {
      return
    }
    setBusy(true)
    try {
      await replanApi.apply(draft.planDate, draft.after, draft.planToken, '在日历里重新安排这一天')
      message.success('已写入新的时间安排。')
      setDraft(null)
      await reload()
    } catch (applyError) {
      message.error(getApiErrorMessage(applyError))
      setDraft(null)
    } finally {
      setBusy(false)
    }
  }

  const days = data?.days ?? []
  const monthCells = days.length > 7 ? days : []
  const weekCells = days.length <= 7 ? days : []

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="CALENDAR / 把时间排开"
        title={
          <>
            先看见时间，
            <br />
            <span className="marker">再安排事情。</span>
          </>
        }
        description="时间块与「今日」计划共用同一份数据；冲突会被后端直接拒绝。"
        actions={
          <div className="calendar-actions">
            <button
              className="paper-inline-button"
              type="button"
              onClick={() => {
                const today = todayLocalDate()
                setCursor(today)
                setSelected(today)
              }}
            >
              回到今天
            </button>
            <button className="paper-inline-button primary" type="button" onClick={() => void previewReplan()} disabled={busy}>
              重排这天
            </button>
          </div>
        }
      />

      {error ? <InlineError message={error} onRetry={() => void load()} /> : null}

      <div className="calendar-toolbar">
        <div className="calendar-views" role="group" aria-label="日历视图">
          {(['month', 'week', 'day'] as CalendarView[]).map((item) => (
            <button
              key={item}
              type="button"
              className={`paper-filter ${view === item ? 'active' : ''}`}
              aria-pressed={view === item}
              onClick={() => setView(item)}
            >
              {item === 'month' ? '月' : item === 'week' ? '周' : '日'}
            </button>
          ))}
        </div>
        <div className="calendar-nav">
          <button className="paper-inline-button" type="button" onClick={() => shift(-1)}>
            ← 上一段
          </button>
          <strong>
            {view === 'month'
              ? dayjs(cursor).format('YYYY 年 M 月')
              : view === 'week'
                ? `${dayjs(range.start).format('M月D日')} ~ ${dayjs(range.end).format('M月D日')}`
                : dayjs(selected).format('YYYY 年 M 月 D 日')}
          </strong>
          <button className="paper-inline-button" type="button" onClick={() => shift(1)}>
            下一段 →
          </button>
        </div>
        <label className="sort-control">
          <span className="sort-prefix">项目</span>
          <select
            aria-label="按项目筛选日历"
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
      </div>

      {loading && !data ? (
        <div className="center-state">
          <Spin size="large" />
          <p>正在摊开日历…</p>
        </div>
      ) : (
        <div className="calendar-grid-layout">
          <SectionCard no="01 /" title="月历" subtitle={`共 ${data?.totalPlannedMinutes ?? 0} 分钟已安排`}>
            {view === 'day' ? (
              <div className="calendar-day-single">
                {(selectedDay?.blocks.length ?? 0) === 0 ? (
                  <p className="muted-note">这一天还没有时间块。</p>
                ) : (
                  <ul className="block-list">
                    {selectedDay?.blocks.map((block) => (
                      <li key={block.id} className="block-row">
                        <span className="block-time">
                          {toAppTimezone(block.startAt).format('HH:mm')}–
                          {toAppTimezone(block.endAt).format('HH:mm')}
                        </span>
                        <span className="block-title">{block.taskTitle}</span>
                        <span className="block-minutes">{minutesOf(block)} 分钟</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ) : (
              <div className={`calendar-month ${view === 'week' ? 'is-week' : ''}`}>
                {WEEK_HEADERS.map((label) => (
                  <div className="calendar-weekday" key={label}>
                    {label}
                  </div>
                ))}
                {(view === 'month' ? monthCells : weekCells).map((day) => {
                  const blocks = day.blocks.length
                  const due = day.dueTasks.length
                  return (
                    <button
                      key={day.date}
                      type="button"
                      className={`calendar-cell ${day.date === selected ? 'is-selected' : ''} ${
                        day.date === todayLocalDate() ? 'is-today' : ''
                      }`}
                      aria-label={`${day.date}，${blocks} 个时间块，${due} 个到期任务`}
                      onClick={() => selectDay(day.date)}
                    >
                      <span className="calendar-date">{dayjs(day.date).format('D')}</span>
                      <span className="calendar-marks">
                        {Array.from({ length: Math.min(blocks, 3) }).map((_, index) => (
                          <i key={`b-${index}`} className="mark-block" />
                        ))}
                        {due > 0 ? <em className="mark-due">{due} 到期</em> : null}
                      </span>
                      {day.plannedMinutes > 0 ? (
                        <small className="calendar-planned">{day.plannedMinutes} 分钟</small>
                      ) : null}
                    </button>
                  )
                })}
              </div>
            )}
          </SectionCard>

          <aside className="calendar-aside">
            <SectionCard
              no="02 /"
              title={dayjs(selected).format('M月D日 dddd')}
              subtitle={
                selectedDay
                  ? `已安排 ${selectedDay.plannedMinutes} 分钟 · 可用 ${selectedDay.availableMinutes} 分钟`
                  : '还没有这一天的数据'
              }
            >
              <div className="block-editor">
                <label className="sort-control">
                  <span className="sort-prefix">任务</span>
                  <select
                    aria-label="为任务安排时间"
                    value={newTaskId}
                    onChange={(event) => setNewTaskId(event.target.value)}
                  >
                    <option value="">选择任务</option>
                    {tasks.map((task) => (
                      <option key={task.id} value={task.id}>
                        {task.title}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="block-time-inputs">
                  <label>
                    开始
                    <input
                      type="time"
                      value={newStart}
                      aria-label="时间块开始时间"
                      onChange={(event) => setNewStart(event.target.value)}
                    />
                  </label>
                  <label>
                    结束
                    <input
                      type="time"
                      value={newEnd}
                      aria-label="时间块结束时间"
                      onChange={(event) => setNewEnd(event.target.value)}
                    />
                  </label>
                  <button
                    className="paper-inline-button"
                    type="button"
                    disabled={busy || !newTaskId}
                    onClick={() => void createBlock()}
                  >
                    安排
                  </button>
                </div>
              </div>

              <h3 className="calendar-subhead">这一天的安排</h3>
              {selectedDay && selectedDay.blocks.length > 0 ? (
                <ul className="block-list">
                  {selectedDay.blocks.map((block) => (
                    <li key={block.id} className="block-row">
                      {editingBlockId === block.id ? (
                        <>
                          <input
                            type="time"
                            value={editStart}
                            aria-label="新的开始时间"
                            onChange={(event) => setEditStart(event.target.value)}
                          />
                          <input
                            type="time"
                            value={editEnd}
                            aria-label="新的结束时间"
                            onChange={(event) => setEditEnd(event.target.value)}
                          />
                          <span className="block-actions">
                            <button
                              className="paper-inline-button"
                              type="button"
                              disabled={busy}
                              onClick={() => void saveEdit(block)}
                            >
                              保存
                            </button>
                            <button
                              className="task-action"
                              type="button"
                              onClick={() => setEditingBlockId(null)}
                            >
                              取消
                            </button>
                          </span>
                        </>
                      ) : (
                        <>
                          <span className="block-time">
                            {toAppTimezone(block.startAt).format('HH:mm')}–
                            {toAppTimezone(block.endAt).format('HH:mm')}
                          </span>
                          <span className="block-title">{block.taskTitle}</span>
                          <span className="block-actions">
                            <button
                              className="task-action"
                              type="button"
                              aria-label={`调整时间块 ${block.taskTitle}`}
                              onClick={() => beginEdit(block)}
                            >
                              调整
                            </button>
                            <button
                              className="task-action danger"
                              type="button"
                              aria-label={`取消时间块 ${block.taskTitle}`}
                              disabled={busy}
                              onClick={() => void removeBlock(block)}
                            >
                              取消
                            </button>
                          </span>
                        </>
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted-note">还没有时间块。</p>
              )}

              <h3 className="calendar-subhead">到期任务</h3>
              {selectedDay && selectedDay.dueTasks.length > 0 ? (
                <ul className="due-task-list">
                  {selectedDay.dueTasks.map((task) => (
                    <li key={task.id}>
                      <span>{task.title}</span>
                      <em className={task.isBlocked ? 'is-blocked' : ''}>
                        {task.isBlocked ? '被依赖阻塞' : formatDueLabel(task.dueAt)}
                      </em>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted-note">这一天没有到期任务。</p>
              )}
            </SectionCard>
          </aside>
        </div>
      )}

      <Modal
        open={draft !== null}
        title="重排这一天的方案"
        okText="写入计划"
        cancelText="先不改"
        confirmLoading={busy}
        onOk={() => void applyReplan()}
        onCancel={() => setDraft(null)}
      >
        {draft ? (
          <div className="replan-preview">
            <ul className="replan-explanation">
              {draft.explanation.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
            <table className="replan-table">
              <thead>
                <tr>
                  <th>任务</th>
                  <th>开始</th>
                  <th>时长</th>
                </tr>
              </thead>
              <tbody>
                {draft.after.map((block) => (
                  <tr key={block.taskId}>
                    <td>{block.title}</td>
                    <td>{toAppTimezone(block.startAt).format('HH:mm')}</td>
                    <td>{block.estimatedMinutes} 分钟</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {draft.blockedTasks.length > 0 ? (
              <p className="muted-note">
                有 {draft.blockedTasks.length} 个任务因为前置任务未完成被跳过。
              </p>
            ) : null}
          </div>
        ) : null}
      </Modal>
    </div>
  )
}
