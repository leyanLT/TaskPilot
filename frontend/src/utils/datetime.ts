import dayjs, { type Dayjs } from 'dayjs'
import timezone from 'dayjs/plugin/timezone'
import utc from 'dayjs/plugin/utc'
import type { Task } from '../types'

dayjs.extend(utc)
dayjs.extend(timezone)

export const APP_TIMEZONE = import.meta.env.VITE_APP_TIMEZONE || 'Asia/Shanghai'

export function toAppTimezone(value: string | Dayjs): Dayjs {
  return dayjs(value).tz(APP_TIMEZONE)
}

export function formatDateTime(value: string | null): string {
  if (!value) {
    return '未设置'
  }
  return toAppTimezone(value).format('YYYY-MM-DD HH:mm')
}

export function formatShortDateTime(value: string | null): string {
  if (!value) {
    return '无截止时间'
  }
  return toAppTimezone(value).format('MM月DD日 HH:mm')
}

export function formatDueLabel(value: string | null): string {
  if (!value) {
    return '没有截止时间'
  }
  const due = toAppTimezone(value)
  const today = toAppTimezone(dayjs())
  if (due.isSame(today, 'day')) {
    return `今天 ${due.format('HH:mm')}`
  }
  if (due.isSame(today.add(1, 'day'), 'day')) {
    return `明天 ${due.format('HH:mm')}`
  }
  if (due.isSame(today.subtract(1, 'day'), 'day')) {
    return `昨天 ${due.format('HH:mm')}`
  }
  if (due.isSame(today, 'year')) {
    return due.format('M月D日 HH:mm')
  }
  return due.format('YYYY年M月D日 HH:mm')
}

export function isTaskOverdue(task: Task, now: Dayjs = dayjs()): boolean {
  return task.status === 'pending' && Boolean(task.dueAt) && dayjs(task.dueAt).isBefore(now)
}

export function toIsoString(value: Dayjs | null | undefined): string | null {
  return value ? value.toISOString() : null
}

export function combineLocalDateTime(date: string, time: string): Dayjs {
  return dayjs.tz(`${date} ${time}`, APP_TIMEZONE)
}

export function todayLocalDate(): string {
  return toAppTimezone(dayjs()).format('YYYY-MM-DD')
}

export function shiftLocalDate(date: string, days: number): string {
  return dayjs(date, 'YYYY-MM-DD').add(days, 'day').format('YYYY-MM-DD')
}

export function isTodayLocal(date: string): boolean {
  return date === todayLocalDate()
}
