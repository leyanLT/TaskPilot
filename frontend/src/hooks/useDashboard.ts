import { useCallback, useEffect, useState } from 'react'
import { getApiErrorMessage } from '../services/http'
import { insightApi } from '../services/reports'
import type { Dashboard } from '../types'

export function useDashboard(reloadKey = 0) {
  const [dashboard, setDashboard] = useState<Dashboard | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await insightApi.dashboard()
      setDashboard(data)
      return true
    } catch (loadError) {
      setError(getApiErrorMessage(loadError))
      return false
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    let active = true
    insightApi
      .dashboard()
      .then((data) => {
        if (active) {
          setDashboard(data)
          setError(null)
        }
      })
      .catch((loadError: unknown) => {
        if (active) {
          setError(getApiErrorMessage(loadError))
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false)
        }
      })
    return () => {
      active = false
    }
  }, [reloadKey])

  return { dashboard, loading, error, reload: load }
}
