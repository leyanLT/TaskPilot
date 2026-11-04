import { useCallback, useEffect, useState } from 'react'
import type { AppRoute } from '../types'

const DEFAULT_PATH = '/assistant'

export function parseRoute(hash: string): AppRoute {
  const clean = hash.replace(/^#/, '').replace(/^\/+/, '')
  const [segment, identifier] = clean.split('/')
  switch (segment) {
    case 'tasks':
      return { name: 'tasks' }
    case 'projects':
      return identifier ? { name: 'project', id: identifier } : { name: 'projects' }
    case 'assistant':
      return { name: 'assistant' }
    case 'today':
      return { name: 'today' }
    case 'calendar':
      return { name: 'calendar' }
    case 'focus':
      return { name: 'focus' }
    case 'settings':
      return { name: 'settings' }
    case 'reports':
      return identifier ? { name: 'report', id: identifier } : { name: 'reports' }
    case 'notifications':
      return { name: 'notifications' }
    case 'dashboard':
    default:
      return { name: 'dashboard' }
  }
}

export function routePath(route: AppRoute): string {
  switch (route.name) {
    case 'tasks':
      return '/tasks'
    case 'projects':
      return '/projects'
    case 'project':
      return `/projects/${route.id}`
    case 'assistant':
      return '/assistant'
    case 'today':
      return '/today'
    case 'calendar':
      return '/calendar'
    case 'focus':
      return '/focus'
    case 'settings':
      return '/settings'
    case 'reports':
      return '/reports'
    case 'report':
      return `/reports/${route.id}`
    case 'notifications':
      return '/notifications'
    case 'dashboard':
    default:
      return DEFAULT_PATH
  }
}

export function navigateTo(path: string): void {
  const next = path.startsWith('#') ? path : `#${path.startsWith('/') ? path : `/${path}`}`
  if (window.location.hash === next) {
    window.dispatchEvent(new HashChangeEvent('hashchange'))
    return
  }
  window.location.hash = next
}

export function useHashRoute() {
  const [route, setRoute] = useState<AppRoute>(() => parseRoute(window.location.hash))

  useEffect(() => {
    const handler = () => setRoute(parseRoute(window.location.hash))
    window.addEventListener('hashchange', handler)
    if (!window.location.hash) {
      window.location.hash = `#${DEFAULT_PATH}`
    }
    return () => window.removeEventListener('hashchange', handler)
  }, [])

  const navigate = useCallback((next: AppRoute) => {
    navigateTo(routePath(next))
  }, [])

  return { route, navigate }
}
