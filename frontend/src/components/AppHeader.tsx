import dayjs from 'dayjs'
import { toAppTimezone } from '../utils/datetime'
import type { AppRoute } from '../types'

interface AppHeaderProps {
  onCreate: () => void
  currentRoute: AppRoute['name']
  unreadCount: number
}

const NAV_ITEMS: Array<{ label: string; path: string; match: AppRoute['name'][] }> = [
  { label: '看板', path: '#/dashboard', match: ['dashboard'] },
  { label: '任务', path: '#/tasks', match: ['tasks'] },
  { label: '项目', path: '#/projects', match: ['projects', 'project'] },
  { label: '日历', path: '#/calendar', match: ['calendar'] },
  { label: '今日', path: '#/today', match: ['today'] },
  { label: '专注', path: '#/focus', match: ['focus'] },
  { label: '报告', path: '#/reports', match: ['reports', 'report'] },
  { label: '小帮手', path: '#/assistant', match: ['assistant'] },
  { label: '设置', path: '#/settings', match: ['settings'] },
]

function partOfDay(hour: number): string {
  if (hour < 6) return '凌晨'
  if (hour < 11) return '早上'
  if (hour < 13) return '午间'
  if (hour < 18) return '午后'
  return '夜'
}

export function AppHeader({ onCreate, currentRoute, unreadCount }: AppHeaderProps) {
  const now = toAppTimezone(dayjs())

  const renderNavLinks = (className: string) => (
    <nav className={className} aria-label="主导航">
      {NAV_ITEMS.map((item) => (
        <a
          key={item.path}
          className={item.match.includes(currentRoute) ? 'active' : ''}
          href={item.path}
        >
          {item.label}
        </a>
      ))}
    </nav>
  )

  return (
    <>
      <header className="app-header">
        <div className="brand" aria-label="TaskPilot">
          <span className="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 32 32" fill="none">
              <path
                d="M18.3 2.5 7.7 17.1h7.4l-1.5 12.4L25 13.1h-7.2l.5-10.6Z"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinejoin="round"
              />
              <path
                d="M9.2 21.7c-2.9 0-5.1 1.6-5.8 4.2"
                stroke="currentColor"
                strokeWidth="1.4"
                strokeLinecap="round"
              />
            </svg>
          </span>
          <div className="brand-lockup">
            <div className="brand-word">TaskPilot</div>
            <span className="brand-note">手边工作台</span>
          </div>
        </div>

        {renderNavLinks('main-nav')}

        <div className="top-actions">
          <a
            className="notification-link"
            href="#/notifications"
            aria-label={
              unreadCount > 0 ? `提醒中心，${unreadCount} 条未读` : '提醒中心，没有未读提醒'
            }
          >
            <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path
                d="M6 10a6 6 0 1 1 12 0c0 4 1.5 5.5 1.5 5.5h-15S6 14 6 10Z"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinejoin="round"
              />
              <path
                d="M10 19a2.2 2.2 0 0 0 4 0"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
              />
            </svg>
            {unreadCount > 0 ? (
              <span className="notification-count">{unreadCount}</span>
            ) : null}
          </a>
          <div className="date-block">
            <strong>{now.format('MM.DD')}</strong>
            <em>
              {now.format('ddd')} / {partOfDay(now.hour())}
            </em>
          </div>
          <button className="new-task-button" type="button" onClick={onCreate}>
            <span aria-hidden="true">＋</span>
            新建任务
          </button>
        </div>
      </header>
      {renderNavLinks('mobile-nav')}
    </>
  )
}
