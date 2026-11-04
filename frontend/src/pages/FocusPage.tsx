/* oxlint-disable react/set-state-in-effect -- data loading on mount; state is set after the request resolves. */
import { App, Spin } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { FocusDial } from '../components/FocusDial'
import { focusMotivation } from '../utils/focus'
import {
  InlineError,
  PageHeader,
  SectionCard,
} from '../components/ui/PaperBits'
import { useFocusSession } from '../hooks/focusSession'
import { getApiErrorMessage } from '../services/http'
import { focusApi, preferenceApi } from '../services/v2'
import { taskApi } from '../services/tasks'
import type { Task } from '../types'
import type { FocusSession, FocusStats, Preferences } from '../types/v2'
import { formatDueLabel } from '../utils/datetime'

const WEEKDAY_LABELS = ['一', '二', '三', '四', '五', '六', '日']

function weekdayLabel(date: string): string {
  const day = new Date(`${date}T00:00:00`).getDay()
  return WEEKDAY_LABELS[(day + 6) % 7]
}

export function FocusPage({
  dataVersion,
  onDataChanged,
}: {
  dataVersion: number
  onDataChanged: () => void
}) {
  const { message } = App.useApp()
  const {
    active,
    elapsedSeconds: elapsed,
    remainingSeconds,
    refresh: refreshFocus,
    pause,
    resume,
    stop,
  } = useFocusSession()
  const [stats, setStats] = useState<FocusStats | null>(null)
  const [tasks, setTasks] = useState<Task[]>([])
  const [preferences, setPreferences] = useState<Preferences | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [lastFinished, setLastFinished] = useState<FocusSession | null>(null)
  const [selectedTaskId, setSelectedTaskId] = useState('')
  const [minutes, setMinutes] = useState(25)
  const [mode, setMode] = useState<'free' | 'pomodoro'>('pomodoro')

  const load = useCallback(async () => {
    setError(null)
    try {
      const [focusStats, pending, prefs] = await Promise.all([
        focusApi.stats(),
        taskApi.list({ status: 'pending' }),
        preferenceApi.get(),
      ])
      setStats(focusStats)
      setTasks(pending)
      setPreferences(prefs)
      setMinutes((current) => (current === 25 ? prefs.defaultFocusMinutes : current))
      setSelectedTaskId((current) => current || pending[0]?.id || '')
    } catch (loadError) {
      setError(getApiErrorMessage(loadError))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load, dataVersion])

  const target = active?.targetSeconds ?? minutes * 60
  const focusedMinutes = active?.taskEstimatedMinutes
    ? Math.max(0, active.taskEstimatedMinutes - Math.floor(elapsed / 60))
    : null

  const refreshNumbers = async () => {
    const [focusStats, pending] = await Promise.all([
      focusApi.stats(),
      taskApi.list({ status: 'pending' }),
    ])
    setStats(focusStats)
    setTasks(pending)
  }

  const startFocus = async () => {
    if (!selectedTaskId) {
      message.warning('先选一个要做的任务。')
      return
    }
    setBusy(true)
    setLastFinished(null)
    try {
      await focusApi.start(selectedTaskId, minutes, mode)
      await refreshFocus()
      message.success(`开始专注 ${minutes} 分钟。`)
      onDataChanged()
      await refreshNumbers()
    } catch (actionError) {
      message.error(getApiErrorMessage(actionError))
    } finally {
      setBusy(false)
    }
  }

  const handlePause = async () => {
    setBusy(true)
    try {
      await pause()
      message.success('已暂停。')
    } catch (actionError) {
      message.error(getApiErrorMessage(actionError))
    } finally {
      setBusy(false)
    }
  }

  const handleResume = async () => {
    setBusy(true)
    try {
      await resume()
      message.success('继续专注。')
    } catch (actionError) {
      message.error(getApiErrorMessage(actionError))
    } finally {
      setBusy(false)
    }
  }

  const handleStop = async () => {
    setBusy(true)
    try {
      const finished = await stop()
      if (finished) {
        setLastFinished(finished)
      }
      message.success('专注结束，时间已记录。')
      onDataChanged()
      await refreshNumbers()
    } catch (actionError) {
      message.error(getApiErrorMessage(actionError))
    } finally {
      setBusy(false)
    }
  }

  if (loading && !stats) {
    return (
      <div className="center-state page-state">
        <Spin size="large" />
        <p>正在铺开专注纸页…</p>
      </div>
    )
  }

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="FOCUS / 专注一下"
        title={
          <>
            把一件事，
            <br />
            <span className="marker">做完整。</span>
          </>
        }
        description={
          stats && stats.todaySeconds > 0
            ? `今天已经专注 ${Math.round(stats.todaySeconds / 60)} 分钟。`
            : '挑一个任务开始，时间由服务端记录，刷新页面也不会丢。'
        }
      />

      {error ? <InlineError message={error} onRetry={() => void load()} /> : null}

      <div className="focus-grid">
        <SectionCard
          no="01 /"
          title={active ? '专注进行中' : '开始一次专注'}
          subtitle={
            active
              ? active.mode === 'pomodoro'
                ? `番茄钟 · 计划 ${active.plannedMinutes} 分钟`
                : '自由专注'
              : `默认 ${preferences?.defaultFocusMinutes ?? 25} 分钟，可调整`
          }
          tone="sticky"
        >
          {active ? (
            <div className="focus-running">
              <p className="focus-task-name">{active.taskTitle}</p>
              <FocusDial
                elapsedSeconds={elapsed}
                targetSeconds={target}
                status={active.status === 'paused' ? 'paused' : 'running'}
                taskTitle={active.taskTitle}
              />
              <p className="focus-motivation" role="status">
                {focusMotivation(
                  active.status === 'paused' ? 'paused' : 'running',
                  remainingSeconds ?? Math.max(0, target - elapsed),
                  target,
                )}
              </p>
              {focusedMinutes !== null ? (
                <p className="focus-remaining-work">
                  按预计耗时估算，这个任务还剩约 {focusedMinutes} 分钟。
                </p>
              ) : (
                <p className="focus-remaining-work">这个任务没有填写预计耗时。</p>
              )}
              <div className="focus-actions">
                {active.status === 'running' ? (
                  <button
                    className="paper-inline-button"
                    type="button"
                    disabled={busy}
                    onClick={() => void handlePause()}
                  >
                    暂停
                  </button>
                ) : (
                  <button
                    className="paper-inline-button primary"
                    type="button"
                    disabled={busy}
                    onClick={() => void handleResume()}
                  >
                    继续
                  </button>
                )}
                <button
                  className="paper-inline-button primary danger"
                  type="button"
                  disabled={busy}
                  onClick={() => void handleStop()}
                >
                  结束专注
                </button>
              </div>
              <p className="muted-note">
                结束专注不会把任务标记为完成，完成与否仍由你自己决定。
              </p>
            </div>
          ) : (
            <div className="focus-setup">
              {lastFinished ? (
                <div className="focus-finished" role="status">
                  <div>
                    <strong>刚刚专注了 {Math.max(1, Math.round(lastFinished.elapsedSeconds / 60))} 分钟</strong>
                    <small>记录已保存到「{lastFinished.taskTitle}」，刷新也不会丢。</small>
                  </div>
                  <span className="focus-finished-stamp" aria-hidden="true">
                    已记录
                  </span>
                </div>
              ) : null}
              <label className="sort-control full-width">
                <span className="sort-prefix">任务</span>
                <select
                  aria-label="选择要专注的任务"
                  value={selectedTaskId}
                  onChange={(event) => setSelectedTaskId(event.target.value)}
                >
                  <option value="">选择一个待完成任务</option>
                  {tasks.map((task) => (
                    <option key={task.id} value={task.id}>
                      {task.title} · {formatDueLabel(task.dueAt)}
                    </option>
                  ))}
                </select>
              </label>
              <div className="focus-setup-row">
                <label className="sort-control">
                  <span className="sort-prefix">时长</span>
                  <select
                    aria-label="专注时长"
                    value={minutes}
                    onChange={(event) => setMinutes(Number(event.target.value))}
                  >
                    {[15, 20, 25, 30, 45, 50, 60, 90].map((value) => (
                      <option key={value} value={value}>
                        {value} 分钟
                      </option>
                    ))}
                  </select>
                </label>
                <label className="focus-mode">
                  <input
                    type="checkbox"
                    checked={mode === 'pomodoro'}
                    onChange={(event) => setMode(event.target.checked ? 'pomodoro' : 'free')}
                  />
                  番茄钟模式
                </label>
              </div>
              <button
                className="paper-inline-button primary"
                type="button"
                disabled={busy || !selectedTaskId}
                onClick={() => void startFocus()}
              >
                开始专注
              </button>
              {tasks.length === 0 ? (
                <p className="muted-note">现在没有待完成任务，先去贴一张便利贴。</p>
              ) : null}
            </div>
          )}
        </SectionCard>

        <SectionCard no="02 /" title="专注记录" subtitle="由服务端时间计算">
          {stats ? (
            <div className="focus-stats">
              <div className="focus-stat-row">
                <div>
                  <strong>{Math.round(stats.todaySeconds / 60)}</strong>
                  <span>今日分钟</span>
                </div>
                <div>
                  <strong>{Math.round(stats.weekSeconds / 60)}</strong>
                  <span>本周分钟</span>
                </div>
                <div>
                  <strong>{stats.sessionCount}</strong>
                  <span>本周会话</span>
                </div>
              </div>
              <div className="focus-bars" aria-label="本周每日专注时长">
                {stats.byDay.map((day) => {
                  const max = Math.max(1, ...stats.byDay.map((item) => item.seconds))
                  return (
                    <div className="focus-bar" key={day.date}>
                      <div className="focus-bar-track">
                        <span
                          className="focus-bar-fill"
                          style={{ height: `${Math.round((day.seconds / max) * 100)}%` }}
                        />
                      </div>
                      <em>{weekdayLabel(day.date)}</em>
                      <small>{Math.round(day.seconds / 60)}</small>
                    </div>
                  )
                })}
              </div>
              <h3 className="focus-subhead">本周专注最多的任务</h3>
              {stats.byTask.length === 0 ? (
                <p className="muted-note">本周还没有专注记录。</p>
              ) : (
                <ul className="focus-task-list">
                  {stats.byTask.map((item) => (
                    <li key={item.taskId}>
                      <span>{item.title}</span>
                      <strong>{Math.round(item.seconds / 60)} 分钟</strong>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ) : (
            <p className="muted-note">还没有专注记录。</p>
          )}
        </SectionCard>
      </div>
    </div>
  )
}
