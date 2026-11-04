import { useCallback, useEffect, useState } from 'react'
import { getApiErrorMessage } from '../services/http'
import { notificationApi } from '../services/notifications'
import type { AppNotification } from '../types'

export function useNotifications(reloadKey = 0) {
  const [items, setItems] = useState<AppNotification[]>([])
  const [unreadCount, setUnreadCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await notificationApi.list()
      setItems(data.items)
      setUnreadCount(data.unreadCount)
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
    notificationApi
      .list()
      .then((data) => {
        if (active) {
          setItems(data.items)
          setUnreadCount(data.unreadCount)
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

  const markRead = useCallback(async (notificationId: string, read = true) => {
    const updated = await notificationApi.markRead(notificationId, read)
    setItems((current) =>
      current.map((item) => (item.id === notificationId ? updated : item)),
    )
    setUnreadCount((current) => {
      if (read && !updated.readAt) {
        return current
      }
      return read
        ? Math.max(0, current - 1)
        : current + 1
    })
    return updated
  }, [])

  const markAllRead = useCallback(async () => {
    const count = await notificationApi.markAllRead()
    setItems((current) =>
      current.map((item) =>
        item.readAt ? item : { ...item, readAt: new Date().toISOString() },
      ),
    )
    setUnreadCount(0)
    return count
  }, [])

  const refresh = useCallback(async () => {
    const data = await notificationApi.refresh()
    setItems(data.items)
    setUnreadCount(data.unreadCount)
    return data
  }, [])

  return {
    items,
    unreadCount,
    loading,
    error,
    reload: load,
    refresh,
    markRead,
    markAllRead,
  }
}
