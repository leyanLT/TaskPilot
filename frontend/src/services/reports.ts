import type {
  Dashboard,
  PrioritySuggestion,
  Report,
  ReportDraft,
  ReportGenerateInput,
  ReportSummary,
  ReportType,
} from '../types'
import { buildApiUrl, request } from './http'
import {
  mapDashboard,
  mapPrioritySuggestion,
  mapReport,
  mapReportDraft,
  mapReportSummary,
  type DashboardDto,
  type PrioritySuggestionDto,
  type ReportDto,
  type ReportDraftDto,
  type ReportSummaryDto,
} from './mappers'

export const insightApi = {
  async dashboard(): Promise<Dashboard> {
    const dto = await request<DashboardDto>('/dashboard')
    return mapDashboard(dto)
  },

  async priorities(limit = 8, projectId?: string): Promise<PrioritySuggestion[]> {
    const suffix = projectId
      ? `?limit=${limit}&project_id=${encodeURIComponent(projectId)}`
      : `?limit=${limit}`
    const dto = await request<{ suggestions: PrioritySuggestionDto[] }>(
      `/insights/priorities${suffix}`,
    )
    return dto.suggestions.map(mapPrioritySuggestion)
  },
}

function reportBody(input: ReportGenerateInput): Record<string, unknown> {
  const body: Record<string, unknown> = { report_type: input.reportType }
  if (input.periodStart) body.period_start = input.periodStart
  if (input.periodEnd) body.period_end = input.periodEnd
  if (input.projectId) body.project_id = input.projectId
  return body
}

export const reportApi = {
  async generate(input: ReportGenerateInput): Promise<ReportDraft> {
    const dto = await request<ReportDraftDto>('/reports/generate', {
      method: 'POST',
      body: JSON.stringify(reportBody(input)),
    })
    return mapReportDraft(dto)
  },

  /** V2.0: real work-time, plan-vs-actual, trend and risk statistics. */
  async generateEnhanced(
    input: ReportGenerateInput & { template?: 'standard' | 'work' },
  ): Promise<ReportDraft> {
    const body = reportBody(input)
    if (input.template) body.template = input.template
    if (!body.period_start || !body.period_end) {
      throw new Error('增强报告需要明确的时间范围。')
    }
    const dto = await request<ReportDraftDto>('/reports/enhanced', {
      method: 'POST',
      body: JSON.stringify(body),
    })
    return mapReportDraft(dto)
  },

  async list(reportType?: ReportType, projectId?: string): Promise<ReportSummary[]> {
    const search = new URLSearchParams()
    if (reportType) search.set('report_type', reportType)
    if (projectId) search.set('project_id', projectId)
    const suffix = search.toString() ? `?${search.toString()}` : ''
    const data = await request<ReportSummaryDto[]>(`/reports${suffix}`)
    return data.map(mapReportSummary)
  },

  async get(reportId: string): Promise<Report> {
    const dto = await request<ReportDto>(`/reports/${encodeURIComponent(reportId)}`)
    return mapReport(dto)
  },

  async save(draft: ReportDraft): Promise<Report> {
    const dto = await request<ReportDto>('/reports', {
      method: 'POST',
      body: JSON.stringify({
        report_type: draft.reportType,
        title: draft.title,
        period_start: draft.periodStart,
        period_end: draft.periodEnd,
        project_id: draft.projectId,
        content_md: draft.contentMd,
        facts: draft.facts,
        ai_used: draft.aiUsed,
      }),
    })
    return mapReport(dto)
  },

  async update(
    reportId: string,
    patch: { title?: string; contentMd?: string },
  ): Promise<Report> {
    const body: Record<string, unknown> = {}
    if (patch.title !== undefined) body.title = patch.title
    if (patch.contentMd !== undefined) body.content_md = patch.contentMd
    const dto = await request<ReportDto>(`/reports/${encodeURIComponent(reportId)}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    })
    return mapReport(dto)
  },

  async remove(reportId: string): Promise<void> {
    await request<void>(`/reports/${encodeURIComponent(reportId)}`, {
      method: 'DELETE',
    })
  },

  async downloadMarkdown(report: Report): Promise<void> {
    const response = await fetch(
      buildApiUrl(`/reports/${encodeURIComponent(report.id)}/markdown`),
    )
    if (!response.ok) {
      throw new Error('导出报告失败，请稍后重试。')
    }
    const text = await response.text()
    const blob = new Blob([text], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${report.title.replace(/[\\/:*?"<>|]/g, '_')}.md`
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(url)
  },
}
