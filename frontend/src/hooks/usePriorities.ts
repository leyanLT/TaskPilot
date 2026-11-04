import { useCallback, useEffect, useState } from 'react'
import { getApiErrorMessage } from '../services/http'
import { insightApi } from '../services/reports'
import type { PrioritySuggestion } from '../types'

export function usePriorities(limit = 8, reloadKey = 0) {
  const [suggestions, setSuggestions] = useState<PrioritySuggestion[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await insightApi.priorities(limit)
      setSuggestions(data)
      return data
    } catch (loadError) {
      setError(getApiErrorMessage(loadError))
      return null
    } finally {
      setLoading(false)
    }
  }, [limit])

  useEffect(() => {
    let active = true
    insightApi
      .priorities(limit)
      .then((data) => {
        if (active) {
          setSuggestions(data)
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
  }, [limit, reloadKey])

  return { suggestions, loading, error, reload: load }
}
