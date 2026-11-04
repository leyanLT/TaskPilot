import { App, DatePicker, Spin } from 'antd'
import dayjs from 'dayjs'
import { useMemo, useState } from 'react'
import { PlanTimeline } from '../components/PlanTimeline'
import {
  EmptyState,
  InlineError,
  PageHeader,
  SectionCard,
  StatTile,
} from '../components/ui/PaperBits'
import { useTasks } from '../hooks/useTasks'
import { usePlan } from '../hooks/usePlan'
import { getApiErrorMessage } from '../services/http'
import { taskApi } from '../services/tasks'
import type { PlanItemInput, PlanSuggestionItem } from '../types'
import {
  APP_TIMEZONE,
  combineLocalDateTime,
  formatDateTime,
  isTodayLocal,
  shiftLocalDate,
  todayLocalDate,
  toAppTimezone,
} from '../utils/datetime'

interface TodayPageProps {
  dataVersion: number
  onDataChanged: () => void
}

function itemsFromPlan(
  planItems: Array<{ taskId: string; startAt: string; endAt: string; note: string | null }>,
): PlanItemInput[] {
  return planItems.map((item) => ({
    taskId: item.taskId,
    startAt: item.startAt,
    endAt: item.endAt,
    note: item.note,
  }))
}

export function TodayPage({ dataVersion, onDataChanged }: TodayPageProps) {
  const { message } = App.useApp()
  const [selectedDate, setSelectedDate] = useState(todayLocalDate())
  const [availableMinutes, setAvailableMinutes] = useState(300)
  const [preview, setPreview] = useState<PlanSuggestionItem[]>([])
  const [busy, setBusy] = useState(false)
  const [busyTaskId, setBusyTaskId] = useState<string | null>(null)
  const [addTaskId, setAddTaskId] = useState('')
  const [addStart, setAddStart] = useState('09:00')
  const [addMinutes, setAddMinutes] = useState(60)

  const { plan, loading, error, reload, savePlan, removePlan, suggest } = usePlan(
    selectedDate,
    dataVersion,
  )
  const { tasks } = useTasks({ reloadKey: dataVersion })

  const pendingTasks = useMemo(
    () => tasks.filter((task) => task.status === 'pending'),
    [tasks],
  )
  const plannedMinutes = plan?.plannedMinutes ?? 0
  const completedBlocks =
    plan?.items.filter((item) => item.taskStatus === 'completed').length ?? 0

  const requirePlan = (): boolean => {
    if (!plan) {
      message.info('这一天还没有计划，先添加一个时间块。')
      return false
    }
    return true
  }

  const persistItems = async (items: PlanItemInput[]) => {
    await savePlan({
      availableMinutes: plan?.availableMinutes ?? availableMinutes,
      items,
    })
  }

  const buildSuggestion = async () => {
    setBusy(true)
    try {
      const result = await suggest(availableMinutes)
      setPreview(result.blocks)
      if (result.blocks.length === 0) {
        message.info('没有可安排的待办任务，或今天剩余时间不足。')
      }
    } catch (suggestError) {
      message.error(getApiErrorMessage(suggestError))
    } finally {
      setBusy(false)
    }
  }

  const adoptSuggestion = async () => {
    setBusy(true)
    try {
      await savePlan({
        availableMinutes,
        items: preview.map((block) => ({
          taskId: block.taskId,
          startAt: block.startAt,
          endAt: block.endAt,
          note: null,
        })),
      })
      setPreview([])
      onDataChanged()
      await reload()
      message.success('已按建议排好今天的时间块。')
    } catch (adoptError) {
      message.error(getApiErrorMessage(adoptError))
    } finally {
      setBusy(false)
    }
  }

  const addManualBlock = async () => {
    if (!addTaskId) {
      message.warning('请选择一个待办任务。')
      return
    }
    const start = combineLocalDateTime(selectedDate, addStart)
    const end = start.add(addMinutes, 'minute')
    const items = plan ? itemsFromPlan(plan.items) : []
    items.push({
      taskId: addTaskId,
      startAt: start.toISOString(),
      endAt: end.toISOString(),
      note: null,
    })
    setBusy(true)
    try {
      await savePlan({ availableMinutes: plan?.availableMinutes ?? availableMinutes, items })
      setAddTaskId('')
      onDataChanged()
      await reload()
      message.success('时间块已加入计划。')
    } catch (addError) {
      message.error(getApiErrorMessage(addError))
    } finally {
      setBusy(false)
    }
  }

  const removeBlock = async (itemId: string) => {
    if (!requirePlan() || !plan) {
      return
    }
    setBusy(true)
    try {
      await persistItems(
        itemsFromPlan(plan.items.filter((item) => item.id !== itemId)),
      )
      onDataChanged()
      await reload()
      message.success('已从计划中移除。')
    } catch (removeError) {
      message.error(getApiErrorMessage(removeError))
    } finally {
      setBusy(false)
    }
  }

  const toggleTask = async (taskId: string, completed: boolean) => {
    setBusyTaskId(taskId)
    try {
      await taskApi.update(taskId, { status: completed ? 'pending' : 'completed' })
      await reload()
      onDataChanged()
      message.success(completed ? '已恢复为待完成。' : '任务已完成。')
    } catch (toggleError) {
      message.error(getApiErrorMessage(toggleError))
    } finally {
      setBusyTaskId(null)
    }
  }

  const clearPlan = async () => {
    setBusy(true)
    try {
      await removePlan()
      setPreview([])
      onDataChanged()
      message.success('今日计划已取消。')
    } catch (clearError) {
      message.error(getApiErrorMessage(clearError))
    } finally {
      setBusy(false)
    }
  }

  const dateLabel = isTodayLocal(selectedDate)
    ? '今天'
    : toAppTimezone(dayjs(selectedDate)).format('M月D日')

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="TODAY / 时间块"
        title={
          <>
            {dateLabel}，
            <br />
            <span className="marker">排成看得见的时间。</span>
          </>
        }
        description={`时区 ${APP_TIMEZONE} · 计划保存后，任务完成状态会同步显示。`}
        actions={
          <div className="date-nav">
            <button
              className="paper-inline-button"
              type="button"
              aria-label="前一天"
              onClick={() => setSelectedDate(shiftLocalDate(selectedDate, -1))}
            >
              ← 前一天
            </button>
            <DatePicker
              value={dayjs(selectedDate, 'YYYY-MM-DD')}
              allowClear={false}
              format="YYYY-MM-DD"
              aria-label="选择计划日期"
              onChange={(value) => {
                if (value) {
                  setSelectedDate(value.format('YYYY-MM-DD'))
                  setPreview([])
                }
              }}
            />
            <button
              className="paper-inline-button"
              type="button"
              aria-label="后一天"
              onClick={() => setSelectedDate(shiftLocalDate(selectedDate, 1))}
            >
              后一天 →
            </button>
            <button
              className="paper-inline-button"
              type="button"
              onClick={() => setSelectedDate(todayLocalDate())}
            >
              回到今天
            </button>
          </div>
        }
      />

      {error ? <InlineError message={error} onRetry={() => void reload()} /> : null}

      <div className="stat-row">
        <StatTile label="可用时间" value={`${availableMinutes} 分`} />
        <StatTile label="已安排" value={`${plannedMinutes} 分`} />
        <StatTile label="时间块" value={plan?.items.length ?? 0} />
        <StatTile
          label="已完成"
          value={`${completedBlocks}/${plan?.items.length ?? 0}`}
          tone="green"
        />
      </div>

      <div className="main-grid today-grid">
        <SectionCard
          no="01 /"
          title={`${selectedDate} 的计划`}
          subtitle={
            plan
              ? `共 ${plan.items.length} 个时间块 · ${plannedMinutes} 分钟`
              : '还没有计划'
          }
          actions={
            plan ? (
              <button
                className="paper-inline-button"
                type="button"
                disabled={busy}
                onClick={() => void clearPlan()}
              >
                取消当天计划
              </button>
            ) : null
          }
        >
          {loading && !plan ? (
            <div className="center-state small">
              <Spin size="small" />
              <p>正在读取计划…</p>
            </div>
          ) : (
            <PlanTimeline
              plan={plan}
              busyTaskId={busyTaskId}
              onToggleTask={(taskId, completed) => void toggleTask(taskId, completed)}
              onRemoveItem={(itemId) => void removeBlock(itemId)}
            />
          )}
        </SectionCard>

        <aside className="today-aside">
          <SectionCard no="02 /" title="按可用时间建议" subtitle="基于真实待办与预计耗时">
            <label className="sort-control full-width">
              <span className="sort-prefix">我有</span>
              <select
                aria-label="今天可用时间"
                value={availableMinutes}
                onChange={(event) => setAvailableMinutes(Number(event.target.value))}
              >
                {[60, 120, 180, 240, 300, 360, 480].map((minutes) => (
                  <option key={minutes} value={minutes}>
                    {minutes / 60} 小时（{minutes} 分钟）
                  </option>
                ))}
              </select>
            </label>
            <div className="hero-actions-row">
              <button
                className="paper-inline-button primary"
                type="button"
                disabled={busy}
                onClick={() => void buildSuggestion()}
              >
                {busy ? '正在计算…' : '生成时间块建议'}
              </button>
              {preview.length > 0 ? (
                <button
                  className="paper-inline-button"
                  type="button"
                  disabled={busy}
                  onClick={() => void adoptSuggestion()}
                >
                  采用建议
                </button>
              ) : null}
            </div>
            {preview.length > 0 ? (
              <ul className="suggestion-preview">
                {preview.map((block) => (
                  <li key={`${block.taskId}-${block.startAt}`}>
                    <span className="plan-time">
                      {toAppTimezone(block.startAt).format('HH:mm')}–
                      {toAppTimezone(block.endAt).format('HH:mm')}
                    </span>
                    <span>{block.title}</span>
                    <small>
                      {block.estimatedMinutes} 分钟
                      {block.isEstimate ? '（估算）' : ''}
                    </small>
                  </li>
                ))}
              </ul>
            ) : null}
            <p className="muted-note">
              估计耗时缺失时按 30 分钟估算；采用前可以先去任务里补充预计耗时。
            </p>
          </SectionCard>

          <SectionCard no="03 /" title="手动加入时间块" subtitle="按顺序排进这一天">
            <label className="sort-control full-width">
              <span className="sort-prefix">任务</span>
              <select
                aria-label="选择要加入计划的任务"
                value={addTaskId}
                onChange={(event) => setAddTaskId(event.target.value)}
              >
                <option value="">选择一个待办任务</option>
                {pendingTasks.map((task) => (
                  <option key={task.id} value={task.id}>
                    {task.title}
                  </option>
                ))}
              </select>
            </label>
            <label className="sort-control full-width">
              <span className="sort-prefix">开始</span>
              <input
                className="paper-input"
                type="time"
                aria-label="时间块开始时间"
                value={addStart}
                onChange={(event) => setAddStart(event.target.value)}
              />
            </label>
            <label className="sort-control full-width">
              <span className="sort-prefix">时长</span>
              <input
                className="paper-input"
                type="number"
                min={5}
                max={480}
                step={5}
                aria-label="时间块时长（分钟）"
                value={addMinutes}
                onChange={(event) => setAddMinutes(Number(event.target.value))}
              />
            </label>
            <button
              className="paper-inline-button primary"
              type="button"
              disabled={busy || !addTaskId}
              onClick={() => void addManualBlock()}
            >
              ＋ 加入计划
            </button>
          </SectionCard>
        </aside>
      </div>

      {!plan && !loading ? (
        <EmptyState
          title="这一天还没有计划"
          description="先给可用时间，再让系统从真实待办里挑出要做的几件事。"
        />
      ) : null}

      {plan ? (
        <p className="muted-note">
          提醒：计划保存时间 {formatDateTime(plan.updatedAt)}，任务完成状态以任务清单为准。
        </p>
      ) : null}
    </div>
  )
}
