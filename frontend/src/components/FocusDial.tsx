import type { CSSProperties } from 'react'

interface FocusDialProps {
  elapsedSeconds: number
  targetSeconds: number
  status: 'running' | 'paused'
  taskTitle: string
}

function pad(value: number): string {
  return String(Math.max(0, Math.floor(value))).padStart(2, '0')
}

function clock(seconds: number): string {
  const safe = Math.max(0, Math.floor(seconds))
  const hours = Math.floor(safe / 3600)
  const minutes = Math.floor((safe % 3600) / 60)
  const rest = safe % 60
  return hours > 0 ? `${pad(hours)}:${pad(minutes)}:${pad(rest)}` : `${pad(minutes)}:${pad(rest)}`
}

export function FocusDial({
  elapsedSeconds,
  targetSeconds,
  status,
  taskTitle,
}: FocusDialProps) {
  const size = 268
  const radius = 112
  const circumference = 2 * Math.PI * radius
  const progress =
    targetSeconds > 0 ? Math.min(1, Math.max(0, elapsedSeconds / targetSeconds)) : 0
  const remaining = Math.max(0, targetSeconds - elapsedSeconds)
  const reached = remaining === 0
  const tone = reached ? 'rust' : remaining <= 300 ? 'amber' : 'leaf'
  const ticks = Array.from({ length: 60 }, (_, index) => index)
  const classes = [
    'focus-dial',
    `tone-${tone}`,
    status === 'paused' ? 'is-paused' : 'is-running',
    reached ? 'is-reached' : '',
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <div className={classes}>
      <div className="focus-dial-halo" aria-hidden="true" />
      <svg
        className="focus-dial-svg"
        viewBox={`0 0 ${size} ${size}`}
        role="timer"
        aria-label={`剩余 ${Math.ceil(remaining / 60)} 分钟，已专注 ${Math.floor(elapsedSeconds / 60)} 分钟`}
      >
        <circle
          className="focus-dial-sketch"
          cx={size / 2}
          cy={size / 2}
          r={radius + 13}
        />
        <circle
          className="focus-dial-track"
          cx={size / 2}
          cy={size / 2}
          r={radius}
        />
        <g className="focus-dial-ticks" aria-hidden="true">
          {ticks.map((tick) => {
            const angle = (tick / 60) * 2 * Math.PI
            const inner = tick % 5 === 0 ? radius + 22 : radius + 25
            const outer = radius + 30
            return (
              <line
                key={tick}
                x1={size / 2 + Math.cos(angle) * inner}
                y1={size / 2 + Math.sin(angle) * inner}
                x2={size / 2 + Math.cos(angle) * outer}
                y2={size / 2 + Math.sin(angle) * outer}
                className={tick % 5 === 0 ? 'is-major' : ''}
              />
            )
          })}
        </g>
        <circle
          className="focus-dial-progress"
          cx={size / 2}
          cy={size / 2}
          r={radius}
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - progress)}
        />
      </svg>

      <div className="focus-dial-center">
        <span className="focus-dial-caption">
          {status === 'paused' ? '已暂停' : reached ? '已达标' : '倒计时'}
        </span>
        <strong className="focus-dial-time" aria-hidden="true">
          {clock(remaining)}
        </strong>
        <span className="focus-dial-foot">
          已专注 {Math.floor(elapsedSeconds / 60)} 分钟 · 目标 {Math.round(targetSeconds / 60)} 分钟
        </span>
      </div>

      {reached ? (
        <span className="focus-confetti" aria-hidden="true">
          {Array.from({ length: 16 }, (_, index) => (
            <i key={index} style={{ '--i': index } as CSSProperties} />
          ))}
        </span>
      ) : null}

      <span className="sr-only">{taskTitle}</span>
    </div>
  )
}
