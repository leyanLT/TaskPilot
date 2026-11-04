/* oxlint-disable react/set-state-in-effect -- the session is synced from the server on mount, on data changes and on focus. */
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { focusApi } from '../services/v2'
import type { FocusSession } from '../types/v2'
import { FocusSessionContext, type FocusSessionContextValue } from '../hooks/focusSession'

const POLL_INTERVAL_MS = 30_000

export function FocusSessionProvider({
  dataVersion,
  children,
}: {
  dataVersion: number
  children: ReactNode
}) {
  const [active, setActive] = useState<FocusSession | null>(null)
  const [loading, setLoading] = useState(true)
  const [nowMs, setNowMs] = useState(() => Date.now())
  const [syncedAt, setSyncedAt] = useState(() => Date.now())

  const refresh = useCallback(async () => {
    try {
      const session = await focusApi.active()
      setActive(session)
      setSyncedAt(Date.now())
    } catch {
      // Offline or backend restart: keep the last known session and let the
      // local clock continue; the next refresh reconciles with the server.
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh, dataVersion])

  useEffect(() => {
    const timer = window.setInterval(() => setNowMs(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    const timer = window.setInterval(() => void refresh(), POLL_INTERVAL_MS)
    const onVisible = () => {
      if (document.visibilityState === 'visible') {
        void refresh()
      }
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [refresh])

  const apply = useCallback((session: FocusSession | null) => {
    setActive(session && session.status !== 'completed' ? session : null)
    setSyncedAt(Date.now())
    return session
  }, [])

  const pause = useCallback(async () => {
    if (!active) {
      return null
    }
    return apply(await focusApi.pause(active.id))
  }, [active, apply])

  const resume = useCallback(async () => {
    if (!active) {
      return null
    }
    return apply(await focusApi.resume(active.id))
  }, [active, apply])

  const stop = useCallback(async () => {
    if (!active) {
      return null
    }
    return apply(await focusApi.stop(active.id))
  }, [active, apply])

  const value = useMemo<FocusSessionContextValue>(() => {
    const drift =
      active?.status === 'running' ? Math.max(0, Math.floor((nowMs - syncedAt) / 1000)) : 0
    const elapsed = active ? active.elapsedSeconds + drift : 0
    const remaining =
      active?.targetSeconds != null ? Math.max(0, active.targetSeconds - elapsed) : null
    return {
      active,
      elapsedSeconds: elapsed,
      remainingSeconds: remaining,
      loading,
      refresh,
      pause,
      resume,
      stop,
    }
  }, [active, nowMs, syncedAt, loading, refresh, pause, resume, stop])

  return (
    <FocusSessionContext.Provider value={value}>{children}</FocusSessionContext.Provider>
  )
}
