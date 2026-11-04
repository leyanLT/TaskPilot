import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ReportsPage } from '../ReportsPage'
import { reportApi } from '../../services/reports'
import { renderWithApp } from '../../test/render'
import { makeProject } from '../../test/fixtures'

vi.mock('../../services/reports', () => ({
  insightApi: {
    dashboard: vi.fn(),
    priorities: vi.fn(),
  },
  reportApi: {
    generate: vi.fn(),
    list: vi.fn(),
    get: vi.fn(),
    save: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    downloadMarkdown: vi.fn(),
  },
}))

const mockedReports = vi.mocked(reportApi)

function makeDraft() {
  return {
    reportType: 'daily' as const,
    title: '2026-11-03 工作日报',
    periodStart: '2026-11-02T16:00:00+00:00',
    periodEnd: '2026-11-03T16:00:00+00:00',
    projectId: null,
    projectName: null,
    contentMd:
      '# 2026-11-03 工作日报\n> 统计范围：2026-11-03 00:00 至 2026-11-04 00:00\n## 一、今日工作概览\n- 完成 2 项任务\n',
    facts: { counts: { completed: 2 } },
    aiUsed: false,
  }
}

function renderLab(onNavigate = vi.fn(), onDataChanged = vi.fn()) {
  return renderWithApp(
    <ReportsPage
      projects={[makeProject()]}
      dataVersion={0}
      onDataChanged={onDataChanged}
      onNavigate={onNavigate}
    />,
  )
}

describe('ReportsPage', () => {
  beforeEach(() => {
    mockedReports.generate.mockReset()
    mockedReports.list.mockReset()
    mockedReports.save.mockReset()
    mockedReports.list.mockResolvedValue([])
  })

  it('generates a factual preview and saves only after confirmation', async () => {
    mockedReports.generate.mockResolvedValue(makeDraft())
    const saved = {
      id: 'report-1',
      ...makeDraft(),
      createdAt: '2026-11-03T12:00:00+00:00',
      updatedAt: '2026-11-03T12:00:00+00:00',
    }
    mockedReports.save.mockResolvedValue(saved)
    const onNavigate = vi.fn()
    const onDataChanged = vi.fn()
    const user = userEvent.setup()
    renderLab(onNavigate, onDataChanged)

    await user.click(screen.getByRole('button', { name: '生成报告草稿' }))

    expect((await screen.findAllByText('2026-11-03 工作日报')).length).toBeGreaterThan(0)
    expect(screen.getByText('一、今日工作概览')).toBeInTheDocument()
    expect(mockedReports.save).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: '确认保存报告' }))

    await waitFor(() => {
      expect(mockedReports.save).toHaveBeenCalledWith(
        expect.objectContaining({ title: '2026-11-03 工作日报' }),
      )
      expect(onNavigate).toHaveBeenCalledWith({ name: 'report', id: 'report-1' })
    })
    expect(onDataChanged).toHaveBeenCalled()
  })

  it('lists saved reports and opens one', async () => {
    mockedReports.list.mockResolvedValue([
      {
        id: 'saved-1',
        reportType: 'weekly',
        title: '第 45 周工作周报',
        periodStart: '2026-11-01T16:00:00+00:00',
        periodEnd: '2026-11-08T16:00:00+00:00',
        projectId: null,
        projectName: null,
        aiUsed: true,
        createdAt: '2026-11-03T12:00:00+00:00',
      },
    ])
    const onNavigate = vi.fn()
    const user = userEvent.setup()
    renderLab(onNavigate)

    expect(await screen.findByText('第 45 周工作周报')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '第 45 周工作周报' }))
    expect(onNavigate).toHaveBeenCalledWith({ name: 'report', id: 'saved-1' })
  })
})
