/* oxlint-disable react/set-state-in-effect -- data loading on mount; state is set after the request resolves. */
import { useCallback, useEffect, useState } from 'react'
import { getApiErrorMessage } from '../services/http'
import { insightApi } from '../services/v2'
import type { Insight } from '../types/v2'

const SEVERITY_LABELS = { high: '需要先处理', medium: '留意一下', low: '有空再看' } as const

export function InsightBoard({
  dataVersion,
  onOpenTask,
}: {
  dataVersion: number
  onOpenTask: (taskId: string) => void
}) {
  const [items, setItems] = useState<Insight[]>([])
  const [dismissed, setDismissed] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [busyKey, setBusyKey] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      const data = await insightApi.list()
      setItems(data.items)
      setDismissed(data.dismissedCount)
    } catch (loadError) {
      setError(getApiErrorMessage(loadError))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load, dataVersion])

  const dismiss = async (key: string) => {
    setBusyKey(key)
    try {
      await insightApi.dismiss(key)
      setItems((current) => current.filter((item) => item.key !== key))
      setDismissed((current) => current + 1)
    } catch (dismissError) {
      setError(getApiErrorMessage(dismissError))
    } finally {
      setBusyKey(null)
    }
  }

  return (
    <div className="insight-board">
      {loading ? <p className="muted-note">正在根据真实数据检查风险…</p> : null}
      {error ? <p className="inline-error-text">{error}</p> : null}
      {!loading && items.length === 0 && !error ? (
        <p className="muted-note">目前没有需要特别留意的任务。</p>
      ) : null}
      <ul className="insight-list">
        {items.slice(0, 4).map((item) => (
          <li key={item.key} className={`insight-item severity-${item.severity}`}>
            <div className="insight-head">
              <span className="insight-severity">{SEVERITY_LABELS[item.severity]}</span>
              <strong>{item.title}</strong>
            </div>
            <p className="insight-reason">{item.reason}</p>
            <p className="insight-suggestion">{item.suggestion}</p>
            <div className="insight-actions">
              {item.taskIds.length > 0 ? (
                <button
                  className="task-action"
                  type="button"
                  onClick={() => onOpenTask(item.taskIds[0])}
                >
                  查看任务
                </button>
              ) : null}
              <button
                className="task-action"
                type="button"
                disabled={busyKey === item.key}
                onClick={() => void dismiss(item.key)}
              >
                今天先不管
              </button>
            </div>
          </li>
        ))}
      </ul>
      {items.length > 4 ? <p className="muted-note">还有 {items.length - 4} 条风险没有展示。</p> : null}
      {dismissed > 0 ? <p className="muted-note">今天已忽略 {dismissed} 条。</p> : null}
      <button className="paper-inline-button" type="button" onClick={() => void load()}>
        重新分析
      </button>
    </div>
  )
}
