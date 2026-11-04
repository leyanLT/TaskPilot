import { App as AntApp, ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import dayjs from 'dayjs'
import 'dayjs/locale/zh-cn'
import { useCallback, useEffect, useState } from 'react'
import { AppHeader } from './components/AppHeader'
import { FocusFloatingTimer } from './components/FocusFloatingTimer'
import { FocusSessionProvider } from './components/FocusSessionProvider'
import { TaskDetailDrawer } from './components/TaskDetailDrawer'
import { TaskFormModal } from './components/TaskFormModal'
import { useHashRoute } from './hooks/useHashRoute'
import { useProjects } from './hooks/useProjects'
import { AssistantPage } from './pages/AssistantPage'
import { CalendarPage } from './pages/CalendarPage'
import { DashboardPage } from './pages/DashboardPage'
import { FocusPage } from './pages/FocusPage'
import { NotificationsPage } from './pages/NotificationsPage'
import { ProjectDetailPage } from './pages/ProjectDetailPage'
import { ProjectsPage } from './pages/ProjectsPage'
import { ReportsPage } from './pages/ReportsPage'
import { SettingsPage } from './pages/SettingsPage'
import { TasksPage } from './pages/TasksPage'
import { TodayPage } from './pages/TodayPage'
import { notificationApi } from './services/notifications'
import { taskApi } from './services/tasks'
import type { AppRoute, Task, TaskInput } from './types'

dayjs.locale('zh-cn')

export default function AppRoot() {
  return (
    <ConfigProvider
      locale={zhCN}
      button={{ autoInsertSpace: false }}
      theme={{
        token: {
          colorPrimary: '#181813',
          colorInfo: '#181813',
          colorSuccess: '#2c6b50',
          colorWarning: '#b36b1c',
          colorError: '#a33f22',
          colorTextBase: '#181813',
          colorBgBase: '#f3eddf',
          colorBgContainer: '#fbf7ed',
          colorBorder: 'rgba(24, 24, 19, 0.34)',
          colorBorderSecondary: 'rgba(24, 24, 19, 0.16)',
          colorTextSecondary: '#5f5a4e',
          borderRadius: 6,
          controlHeight: 38,
          fontFamily:
            '"Microsoft YaHei", "PingFang SC", "Segoe UI", "Helvetica Neue", sans-serif',
          boxShadow: '4px 4px 0 rgba(24, 24, 19, 0.12)',
        },
        components: {
          Button: {
            primaryShadow: 'none',
            defaultShadow: 'none',
            fontWeight: 600,
          },
          Checkbox: {
            colorPrimary: '#181813',
            colorPrimaryHover: '#181813',
          },
          Modal: {
            contentBg: '#fbf7ed',
            headerBg: 'transparent',
          },
          Input: {
            activeBorderColor: '#181813',
            hoverBorderColor: '#181813',
            activeShadow: '0 0 0 2px rgba(220, 239, 114, 0.7)',
          },
          DatePicker: {
            activeBorderColor: '#181813',
            hoverBorderColor: '#181813',
            activeShadow: '0 0 0 2px rgba(220, 239, 114, 0.7)',
          },
          Message: {
            contentBg: '#fbf7ed',
          },
        },
      }}
    >
      <AntApp>
        <AppShell />
      </AntApp>
    </ConfigProvider>
  )
}

function AppShell() {
  const { message } = AntApp.useApp()
  const { route, navigate } = useHashRoute()
  const [dataVersion, setDataVersion] = useState(0)
  const [unreadCount, setUnreadCount] = useState(0)
  const [drawerTaskId, setDrawerTaskId] = useState<string | null>(null)
  const [taskModalOpen, setTaskModalOpen] = useState(false)
  const [editingTask, setEditingTask] = useState<Task | null>(null)
  const { projects, reload: reloadProjects } = useProjects({ includeArchived: true })

  const refreshUnread = useCallback(async () => {
    try {
      setUnreadCount(await notificationApi.unreadCount())
    } catch {
      // Reminder counts are decorative; failures must not break the page.
    }
  }, [])

  const markDataChanged = useCallback(() => {
    setDataVersion((current) => current + 1)
    void refreshUnread()
    void reloadProjects()
  }, [refreshUnread, reloadProjects])

  useEffect(() => {
    let active = true
    notificationApi
      .unreadCount()
      .then((count) => {
        if (active) {
          setUnreadCount(count)
        }
      })
      .catch(() => undefined)
    const timer = window.setInterval(() => {
      notificationApi
        .unreadCount()
        .then((count) => setUnreadCount(count))
        .catch(() => undefined)
    }, 60_000)
    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [])

  useEffect(() => {
    let active = true
    notificationApi
      .unreadCount()
      .then((count) => {
        if (active) {
          setUnreadCount(count)
        }
      })
      .catch(() => undefined)
    return () => {
      active = false
    }
  }, [route])

  const openCreateTask = () => {
    setEditingTask(null)
    setTaskModalOpen(true)
  }

  const handleTaskSubmit = async (input: TaskInput) => {
    if (editingTask) {
      await taskApi.update(editingTask.id, input)
      message.success('任务已更新。')
    } else {
      await taskApi.create(input)
      message.success('任务已创建。')
    }
    setTaskModalOpen(false)
    setEditingTask(null)
    markDataChanged()
  }

  const openTask = (taskId: string) => setDrawerTaskId(taskId)

  const go = (next: AppRoute) => {
    setDrawerTaskId(null)
    navigate(next)
  }

  const routeKey = `${route.name}-${'id' in route ? route.id : ''}`

  return (
    <FocusSessionProvider dataVersion={dataVersion}>
      <div className="app-shell">
      <div className="paper-page">
        <AppHeader
          onCreate={openCreateTask}
          currentRoute={route.name}
          unreadCount={unreadCount}
        />
        <svg
          className="rough-divider"
          viewBox="0 0 1350 12"
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          <path
            d="M2 7.5c81-1.6 154-2.2 230-1.4 95 .9 162 2.4 245 1.1 95-1.4 188-2.1 278-1.1 91 1 177 2.1 272 1.4 107-.8 188-2.1 321-3.2"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.2"
            strokeLinecap="round"
          />
        </svg>

        <main className="page-content" key={routeKey}>
          {route.name === 'dashboard' ? (
            <DashboardPage
              dataVersion={dataVersion}
              onOpenTask={openTask}
              onNavigate={go}
            />
          ) : null}
          {route.name === 'tasks' ? (
            <TasksPage
              projects={projects}
              dataVersion={dataVersion}
              onOpenTask={openTask}
              onDataChanged={markDataChanged}
            />
          ) : null}
          {route.name === 'projects' ? (
            <ProjectsPage
              dataVersion={dataVersion}
              onDataChanged={markDataChanged}
              onNavigate={go}
            />
          ) : null}
          {route.name === 'project' ? (
            <ProjectDetailPage
              projectId={route.id}
              projects={projects}
              dataVersion={dataVersion}
              onDataChanged={markDataChanged}
              onNavigate={go}
            />
          ) : null}
          {route.name === 'assistant' ? (
            <AssistantPage
              projects={projects}
              onDataChanged={markDataChanged}
              onNavigate={go}
            />
          ) : null}
          {route.name === 'today' ? (
            <TodayPage dataVersion={dataVersion} onDataChanged={markDataChanged} />
          ) : null}
          {route.name === 'calendar' ? (
            <CalendarPage
              projects={projects}
              dataVersion={dataVersion}
              onDataChanged={markDataChanged}
            />
          ) : null}
          {route.name === 'focus' ? (
            <FocusPage dataVersion={dataVersion} onDataChanged={markDataChanged} />
          ) : null}
          {route.name === 'settings' ? <SettingsPage /> : null}
          {route.name === 'reports' ? (
            <ReportsPage
              projects={projects}
              dataVersion={dataVersion}
              onDataChanged={markDataChanged}
              onNavigate={go}
            />
          ) : null}
          {route.name === 'report' ? (
            <ReportsPage
              reportId={route.id}
              projects={projects}
              dataVersion={dataVersion}
              onDataChanged={markDataChanged}
              onNavigate={go}
            />
          ) : null}
          {route.name === 'notifications' ? (
            <NotificationsPage
              dataVersion={dataVersion}
              onOpenTask={openTask}
              onDataChanged={markDataChanged}
            />
          ) : null}
        </main>

        <footer className="app-footer">
          <span>TaskPilot V2.0 / personal work notebook</span>
          <span className="footer-quote">把日子过成一张可以涂改的纸。</span>
          <span>数据保存在 SQLite · 单用户本地应用</span>
        </footer>
      </div>

      <TaskDetailDrawer
        taskId={drawerTaskId}
        projects={projects}
        onClose={() => setDrawerTaskId(null)}
        onEdit={(task) => {
          setDrawerTaskId(null)
          setEditingTask(task)
          setTaskModalOpen(true)
        }}
        onChanged={markDataChanged}
      />

      <TaskFormModal
        open={taskModalOpen}
        task={editingTask}
        projects={projects}
        onCancel={() => {
          setTaskModalOpen(false)
          setEditingTask(null)
        }}
        onSubmit={handleTaskSubmit}
      />

        <FocusFloatingTimer
          hidden={route.name === 'focus'}
          onChanged={markDataChanged}
        />
      </div>
    </FocusSessionProvider>
  )
}
