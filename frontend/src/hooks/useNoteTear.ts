import { useCallback, useEffect, useRef, useState } from 'react'
import { NOTE_LAND_MS, NOTE_TEAR_MS, delay } from '../utils/motion'

export interface TearingNote<T> {
  item: T
  /** Where the note sat when the reader tore it, so the grid can hold its slot. */
  index: number
}

/**
 * Runs the tear motion around one async write.
 *
 * The write starts immediately; the shredded paper keeps falling for at least
 * NOTE_TEAR_MS so a fast local API never cuts the animation in half. When the
 * write fails the pieces snap back and the note is readable again.
 */
export function useNoteTear<T extends { id: string }>(run: (item: T) => Promise<void>) {
  const [tearing, setTearing] = useState<TearingNote<T> | null>(null)
  const [landingId, setLandingId] = useState<string | null>(null)
  const landingTimer = useRef<number | null>(null)

  useEffect(() => {
    return () => {
      if (landingTimer.current !== null) {
        window.clearTimeout(landingTimer.current)
      }
    }
  }, [])

  const tear = useCallback(
    async (item: T, index: number) => {
      if (tearing) {
        return
      }
      setTearing({ item, index })
      const startedAt = Date.now()
      try {
        await run(item)
      } catch {
        setTearing(null)
        return
      }
      const remaining = NOTE_TEAR_MS - (Date.now() - startedAt)
      if (remaining > 0) {
        await delay(remaining)
      }
      setTearing(null)
      setLandingId(item.id)
      if (landingTimer.current !== null) {
        window.clearTimeout(landingTimer.current)
      }
      landingTimer.current = window.setTimeout(() => setLandingId(null), NOTE_LAND_MS)
    },
    [run, tearing],
  )

  return { tearing, landingId, tear }
}
