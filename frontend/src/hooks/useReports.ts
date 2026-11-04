import { useCallback, useEffect, useState } from 'react'
import { getApiErrorMessage } from '../services/http'
import { reportApi } from '../services/reports'
import type { ReportSummary } from '../types'

export function useReports(reloadKey = 0) {
  const [reports, setReports] = useState<ReportSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await reportApi.list()
      setReports(data)
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
    reportApi
      .list()
      .then((data) => {
        if (active) {
          setReports(data)
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

  const removeReport = useCallback(async (reportId: string) => {
    await reportApi.remove(reportId)
    setReports((current) => current.filter((report) => report.id !== reportId))
  }, [])

  return { reports, loading, error, reload: load, removeReport }
}
