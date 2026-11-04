import { App } from 'antd'
import { useState } from 'react'
import { useFocusSession } from '../hooks/focusSession'
import { getApiErrorMessage } from '../services/http'

function pad(value: number): string {
  return String(Math.max(0, Math.floor(value))).padStart(2, '0')
}

function clock(seconds: number | null): string {
  if (seconds === null) {
    return '--:--'
  }
  const safe = Math.max(0, Math.floor(seconds))
  const minutes = Math.floor(safe / 60)
  const rest = safe % 60
  return `${pad(minutes)}:${pad(rest)}`
}

export function FocusFloatingTimer({
  hidden,
  onChanged,
}: {
  hidden: boolean
  onChanged: () => void
}) {
  const { message } = App.useApp()
  const { active, elapsedSeconds, remainingSeconds, pause, resume, stop } =
    useFocusSession()
  const [busy, setBusy] = useState(false)

  if (!active || hidden) {
    return null
  }

  const target = active.targetSeconds ?? 0
  const progress = target > 0 ? Math.min(1, elapsedSeconds / target) : 0
  const circumference = 2 * Math.PI * 21
  const reached = remainingSeconds === 0
  const paused = active.status === 'paused'

  const run = async (action: () => Promise<unknown>, success: string) => {
    setBusy(true)
    try {
      await action()
      message.success(success)
      onChanged()
    } catch (error) {
      message.error(getApiErrorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <aside
      className={`focus-float ${paused ? 'is-paused' : 'is-running'} ${
        reached ? 'is-reached' : ''
      }`}
      aria-label="专注倒计时悬浮窗"
    >
      <a className="focus-float-main" href="#/focus" aria-label={`回到专注页，${active.taskTitle}`}>
        <span className="focus-float-ring" aria-hidden="true">
          <svg viewBox="0 0 52 52">
            <circle className="focus-float-track" cx="26" cy="26" r="21" />
            <circle
              className="focus-float-progress"
              cx="26"
              cy="26"
              r="21"
              strokeDasharray={circumference}
              strokeDashoffset={circumference * (1 - progress)}
            />
          </svg>
          <em>{paused ? '❙❙' : reached ? '✓' : '●'}</em>
        </span>
        <span className="focus-float-copy">
          <strong>{clock(remainingSeconds)}</strong>
          <span>{active.taskTitle}</span>
          <small>
            {paused ? '已暂停' : reached ? '已达标，可以收尾' : '专注中'} · 已做{' '}
            {Math.floor(elapsedSeconds / 60)} 分钟
          </small>
        </span>
      </a>
      <div className="focus-float-actions">
        <button
          type="button"
          className="focus-float-button"
          disabled={busy}
          aria-label={paused ? '继续专注' : '暂停专注'}
          onClick={() =>
            void run(
              paused ? () => resume() : () => pause(),
              paused ? '继续专注。' : '已暂停。',
            )
          }
        >
          {paused ? '继续' : '暂停'}
        </button>
        <button
          type="button"
          className="focus-float-button is-danger"
          disabled={busy}
          aria-label="结束专注"
          onClick={() => void run(() => stop(), '专注结束，时间已记录。')}
        >
          结束
        </button>
      </div>
    </aside>
  )
}
