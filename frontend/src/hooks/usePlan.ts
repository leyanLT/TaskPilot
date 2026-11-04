import { useCallback, useEffect, useState } from 'react'
import { getApiErrorMessage } from '../services/http'
import { planApi, type PlanInput } from '../services/plans'
import type { Plan, PlanSuggestion } from '../types'

export function usePlan(planDate: string, reloadKey = 0) {
  const [plan, setPlan] = useState<Plan | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await planApi.get(planDate)
      setPlan(data)
      return data
    } catch (loadError) {
      setError(getApiErrorMessage(loadError))
      return null
    } finally {
      setLoading(false)
    }
  }, [planDate])

  useEffect(() => {
    let active = true
    planApi
      .get(planDate)
      .then((data) => {
        if (active) {
          setPlan(data)
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
  }, [planDate, reloadKey])

  const savePlan = useCallback(
    async (input: PlanInput) => {
      const saved = await planApi.save(planDate, input)
      setPlan(saved)
      return saved
    },
    [planDate],
  )

  const removePlan = useCallback(async () => {
    await planApi.remove(planDate)
    setPlan(null)
  }, [planDate])

  const suggest = useCallback(
    async (availableMinutes: number): Promise<PlanSuggestion> =>
      planApi.suggestion(planDate, availableMinutes),
    [planDate],
  )

  return { plan, loading, error, reload: load, savePlan, removePlan, suggest }
}
