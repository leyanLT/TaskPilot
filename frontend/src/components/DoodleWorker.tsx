interface DoodleWorkerProps {
  className?: string
}

/** Original marker-line micro worker: no face, rough joins, one carrying gesture. */
export function DoodleWorker({ className }: DoodleWorkerProps) {
  return (
    <svg
      className={className}
      viewBox="0 0 120 120"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      <g
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="butt"
        strokeLinejoin="miter"
      >
        <path d="M37 31c-4-10 5-17 13-16 3-7 14-8 18-2 8-1 13 7 9 13 7 4 4 13-2 15-2 7-9 10-15 8-6 5-15 1-16-5-7-1-10-6-7-12" />
        <path d="M42 48c-2 10-3 17-3 25m25-25c3 8 5 16 5 25" />
        <path d="M34 62c-7 4-10 8-11 13m43-14c7 4 12 6 18 5" />
        <path d="M37 73c-3 9-6 15-11 21m33-21c4 7 9 13 15 18" />
        <path d="M72 57 88 43l11 12-16 14z" />
        <path d="m84 46 3 4m2-1 4 4m-14 3 9-8" />
        <path d="M30 26c-3-8-8-11-13-12m17 2-.5 7" />
      </g>
      <path
        d="M25 19c-8-3-12-1-15 3"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  )
}
