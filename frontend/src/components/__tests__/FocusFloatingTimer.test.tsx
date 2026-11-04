import { describe, expect, it, vi } from 'vitest'
import { cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { FocusFloatingTimer } from '../FocusFloatingTimer'
import { FocusSessionContext } from '../../hooks/focusSession'
import { renderWithApp } from '../../test/render'
import type { FocusSession } from '../../types/v2'

function makeSession(overrides: Partial<FocusSession> = {}): FocusSession {
  return {
    id: 'focus-1',
    taskId: 'task-1',
    taskTitle: '写周报',
    taskEstimatedMinutes: 60,
    status: 'running',
    mode: 'pomodoro',
    plannedMinutes: 25,
    elapsedSeconds: 300,
    accumulatedSeconds: 300,
    targetSeconds: 1500,
    remainingSeconds: 1200,
    startedAt: '2026-11-04T02:00:00Z',
    lastResumedAt: '2026-11-04T02:00:00Z',
    endedAt: null,
    syncedAt: '2026-11-04T02:05:00Z',
    ...overrides,
  }
}

function renderFloat(
  options: {
    hidden?: boolean
    session?: FocusSession | null
    pause?: () => Promise<FocusSession | null>
    stop?: () => Promise<FocusSession | null>
  } = {},
) {
  const session = options.session === undefined ? makeSession() : options.session
  const pause = options.pause ?? vi.fn().mockResolvedValue(null)
  const stop = options.stop ?? vi.fn().mockResolvedValue(null)
  const value = {
    active: session,
    elapsedSeconds: session?.elapsedSeconds ?? 0,
    remainingSeconds: session?.remainingSeconds ?? null,
    loading: false,
    refresh: vi.fn(),
    pause,
    resume: vi.fn().mockResolvedValue(null),
    stop,
  }
  renderWithApp(
    <FocusSessionContext.Provider value={value}>
      <FocusFloatingTimer hidden={options.hidden ?? false} onChanged={vi.fn()} />
    </FocusSessionContext.Provider>,
  )
  return { pause, stop }
}

describe('FocusFloatingTimer', () => {
  it('shows the remaining time and task while another page is open', () => {
    renderFloat()
    expect(screen.getByText('20:00')).toBeInTheDocument()
    expect(screen.getByText('写周报')).toBeInTheDocument()
    expect(screen.getByLabelText('专注倒计时悬浮窗')).toBeInTheDocument()
    expect(screen.getByText('专注中 · 已做 5 分钟')).toBeInTheDocument()
  })

  it('pauses and stops from the floating window', async () => {
    const user = userEvent.setup()
    const { pause, stop } = renderFloat()
    await user.click(screen.getByRole('button', { name: '暂停专注' }))
    expect(pause).toHaveBeenCalledTimes(1)
    await user.click(screen.getByRole('button', { name: '结束专注' }))
    expect(stop).toHaveBeenCalledTimes(1)
  })

  it('is hidden on the focus page and when no session is active', () => {
    renderFloat({ hidden: true })
    expect(screen.queryByLabelText('专注倒计时悬浮窗')).not.toBeInTheDocument()
    cleanup()
    renderFloat({ session: null })
    expect(screen.queryByLabelText('专注倒计时悬浮窗')).not.toBeInTheDocument()
  })

  it('marks a reached target without stopping the session', () => {
    renderFloat({
      session: makeSession({ remainingSeconds: 0, elapsedSeconds: 1500 }),
    })
    expect(screen.getByText('00:00')).toBeInTheDocument()
    expect(screen.getByText('已达标，可以收尾 · 已做 25 分钟')).toBeInTheDocument()
  })

  it('links back to the focus page', () => {
    renderFloat()
    expect(screen.getByRole('link', { name: '回到专注页，写周报' })).toHaveAttribute(
      'href',
      '#/focus',
    )
  })
})
