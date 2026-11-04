import type { AppNotification, NotificationList } from '../types'
import { request } from './http'
import { mapNotification, mapNotificationList } from './mappers'
import type { NotificationDto, NotificationListDto } from './mappers'

export const notificationApi = {
  async list(unreadOnly = false): Promise<NotificationList> {
    const suffix = unreadOnly ? '?unread_only=true' : ''
    const dto = await request<NotificationListDto>(`/notifications${suffix}`)
    return mapNotificationList(dto)
  },

  async unreadCount(): Promise<number> {
    const dto = await request<{ count: number }>('/notifications/unread-count')
    return dto.count
  },

  async refresh(): Promise<NotificationList> {
    const dto = await request<NotificationListDto>('/notifications/refresh', {
      method: 'POST',
    })
    return mapNotificationList(dto)
  },

  async markRead(notificationId: string, read = true): Promise<AppNotification> {
    const dto = await request<NotificationDto>(
      `/notifications/${encodeURIComponent(notificationId)}`,
      { method: 'PATCH', body: JSON.stringify({ read }) },
    )
    return mapNotification(dto)
  },

  async markAllRead(): Promise<number> {
    const dto = await request<{ count: number }>('/notifications/read-all', {
      method: 'POST',
    })
    return dto.count
  },
}
