/** Translucent washi tape holding a note to the page. */
export function NoteTape({ peeled = false }: { peeled?: boolean }) {
  return (
    <span
      className={`note-tape ${peeled ? 'is-peeled' : ''}`}
      aria-hidden="true"
      data-testid="note-tape"
    />
  )
}

/**
 * The shredding layers used while a note is torn off: two ragged paper halves,
 * a pale rip seam and a few paper fibres. Purely decorative.
 */
export function NoteTearBurst() {
  return (
    <span className="note-tear-run" aria-hidden="true" data-testid="tear-burst">
      <i className="tear-half is-top" />
      <i className="tear-half is-bottom" />
      <i className="tear-seam" />
      <i className="tear-shard is-one" />
      <i className="tear-shard is-two" />
      <i className="tear-shard is-three" />
    </span>
  )
}

/** Ink-line micro worker pressing a fresh note onto the page, in the Paper Day hand. */
export function EmptyWallDoodle() {
  return (
    <svg
      className="wall-doodle"
      viewBox="0 0 168 132"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      <g
        stroke="var(--ink)"
        strokeWidth="2.4"
        strokeLinecap="butt"
        strokeLinejoin="miter"
      >
        {/* the note being pressed down */}
        <path
          d="M26 44c9-1 18-2 27-2 8 0 16 1 24 2 1 12 2 23 2 33-16 2-33 2-49 1-2-11-3-23-4-34Z"
          fill="var(--note)"
        />
        {/* tape across the note's top edge */}
        <path d="M40 34c6-2 12-2 18-1 6 1 11 2 16 3-6 2-12 3-18 2-5 0-11-2-16-4Z" fill="var(--lime)" />
        {/* three short lines of writing on the note */}
        <path d="M36 57c9-2 19-2 28-1M35 64c6-1 13-1 19 0M35 71c5-1 10-1 14 0" strokeWidth="1.6" />
        {/* worker leaning in from the right, one palm flat on the note */}
        <path d="M112 33c-3-8 4-14 11-13 2-6 11-7 15-2 7-1 11 6 8 11 6 3 4 11-1 13-2 6-8 8-13 6-5 4-13 1-14-4-6-1-8-5-6-11" />
        <path d="M116 47c-3 8-4 15-4 22m20-22c3 7 4 14 4 22" />
        <path d="M112 55c-6 1-10 3-13 5" />
        <path d="M99 60c-6 0-11-1-15-3" />
        <path d="M136 56c6 2 10 5 12 9" />
        <path d="M113 69c-2 8-5 13-9 18m27-18c3 7 6 13 11 17" />
        <path d="M101 89c-4 0-7 1-9 3m36-3c3 0 5 1 7 3" />
      </g>
      {/* cheap motion marks: the note is being pushed, not drawn from nothing */}
      <g stroke="var(--ink)" strokeWidth="1.6" strokeLinecap="round">
        <path d="M14 40c2-3 3-5 3-8M10 51c3-1 5-2 7-4" />
        <path d="M45 96c5-2 10-3 15-3" strokeDasharray="3 7" />
      </g>
    </svg>
  )
}

/** Small hand-drawn scissors mark for the tear action. */
export function ScissorsMark() {
  return (
    <svg className="scissors-mark" viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <g stroke="currentColor" strokeWidth="1.4" strokeLinecap="round">
        <circle cx="5.2" cy="6" r="2.3" />
        <circle cx="5.2" cy="14" r="2.3" />
        <path d="M7.2 7.4 16 16M7.2 12.6 16 4" />
      </g>
    </svg>
  )
}
