/** Shared timing and small helpers for the sticky-note paper motion. */

export const NOTE_PASTE_MS = 640
export const NOTE_TEAR_MS = 540
export const NOTE_LAND_MS = 420

/** How long after creation a note still greets the reader with the "paste" motion. */
const FRESH_PASTE_WINDOW_MS = 8000

export function delay(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms)
  })
}

export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return false
  }
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/** A note created a moment ago was just pasted onto the page. */
export function isFreshlyPasted(createdAt: string, now = Date.now()): boolean {
  const stamp = Date.parse(createdAt)
  if (Number.isNaN(stamp)) {
    return false
  }
  const age = now - stamp
  return age >= 0 && age < FRESH_PASTE_WINDOW_MS
}

/**
 * Stable per-note tilt. Hand-taped notes are never perfectly straight, but the
 * angle must not change between renders, so it comes from the id, not Math.random.
 */
export function noteTilt(id: string): number {
  const tilts = [-1.8, -1.1, -0.55, 0.25, 0.8, 1.25, 1.75]
  let hash = 0
  for (let index = 0; index < id.length; index += 1) {
    hash = (hash * 31 + id.charCodeAt(index)) | 0
  }
  return tilts[Math.abs(hash) % tilts.length]
}

/** Paper tone for a note: mostly butter yellow, sometimes pale lime. */
export function noteTone(id: string): 'butter' | 'lime' {
  let hash = 0
  for (let index = 0; index < id.length; index += 1) {
    hash = (hash * 17 + id.charCodeAt(index) * 7) | 0
  }
  return Math.abs(hash) % 10 < 7 ? 'butter' : 'lime'
}
