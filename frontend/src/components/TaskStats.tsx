interface TaskStatsProps {
  total: number
  pending: number
  completed: number
  overdue: number
}

function padCount(value: number): string {
  return String(value).padStart(2, '0')
}

export function TaskStats({ total, pending, completed, overdue }: TaskStatsProps) {
  const items = [
    { label: '全部任务', value: total, className: 'count-total' },
    { label: '待完成', value: pending, className: 'count-pending' },
    { label: '已完成', value: completed, className: 'count-completed' },
    { label: '已逾期', value: overdue, className: 'count-overdue' },
  ]

  return (
    <aside className="hero-side" aria-label="任务统计">
      <div className="margin-note">
        <strong>今天的边角料</strong>
        做完一件，就划掉一件。
        <br />
        不用很满，也很好。
        <svg viewBox="0 0 50 38" fill="none" aria-hidden="true">
          <path
            d="M4 4c16 0 27 6 31 21"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
          />
          <path
            d="m30 20 6 7 7-5"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </div>
      <div className="counts">
        {items.map((item) => (
          <div className={`count ${item.className}`} key={item.label}>
            <strong>{padCount(item.value)}</strong>
            <span>{item.label}</span>
          </div>
        ))}
      </div>
    </aside>
  )
}
