import { createContext, useContext } from 'react'
import type { FocusSession } from '../types/v2'

export interface FocusSessionContextValue {
  active: FocusSession | null
  elapsedSeconds: number
  remainingSeconds: number | null
  loading: boolean
  refresh: () => Promise<void>
  pause: () => Promise<FocusSession | null>
  resume: () => Promise<FocusSession | null>
  stop: () => Promise<FocusSession | null>
}

export const FocusSessionContext = createContext<FocusSessionContextValue | null>(null)

export function useFocusSession(): FocusSessionContextValue {
  const value = useContext(FocusSessionContext)
  if (!value) {
    throw new Error('useFocusSession 必须在 FocusSessionProvider 内使用')
  }
  return value
}
