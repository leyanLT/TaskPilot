import { App, DatePicker, Select, Spin } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import { useCallback, useEffect, useState } from 'react'
import { ReportContent } from '../components/ReportContent'
import {
  EmptyState,
  InlineError,
  PageHeader,
  SectionCard,
} from '../components/ui/PaperBits'
import { useReports } from '../hooks/useReports'
import { getApiErrorMessage } from '../services/http'
import { reportApi } from '../services/reports'
import { reportDownloadUrl } from '../services/v2'
import {
  REPORT_TYPE_LABELS,
  type AppRoute,
  type Project,
  type Report,
  type ReportDraft,
  type ReportType,
} from '../types'
import { formatDateTime, toAppTimezone } from '../utils/datetime'

interface ReportsPageProps {
  reportId?: string
  projects: Project[]
  dataVersion: number
  onDataChanged: () => void
  onNavigate: (route: AppRoute) => void
}

const REPORT_TYPES: Array<{ label: string; value: ReportType }> = [
  { label: '每日工作总结', value: 'daily' },
  { label: '每周工作总结', value: 'weekly' },
  { label: '项目进度报告', value: 'project' },
]

function ReportDetailView({
  reportId,
  onNavigate,
  onDataChanged,
}: {
  reportId: string
  onNavigate: (route: AppRoute) => void
  onDataChanged: () => void
}) {
  const { message } = App.useApp()
  const [report, setReport] = useState<Report | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [draftContent, setDraftContent] = useState('')
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await reportApi.get(reportId)
      setReport(data)
      setDraftContent(data.contentMd)
      return data
    } catch (loadError) {
      setError(getApiErrorMessage(loadError))
      return null
    } finally {
      setLoading(false)
    }
  }, [reportId])

  useEffect(() => {
    let active = true
    reportApi
      .get(reportId)
      .then((data) => {
        if (active) {
          setReport(data)
          setDraftContent(data.contentMd)
          setError(null)
        }
      })
      .catch((loadError: unknown) => {
        if (active) {
          setError(getApiErrorMessage(loadError))
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false)
        }
      })
    return () => {
      active = false
    }
  }, [reportId])

  const save = async () => {
    if (!report) {
      return
    }
    setSaving(true)
    try {
      const updated = await reportApi.update(report.id, { contentMd: draftContent })
      setReport(updated)
      setEditing(false)
      onDataChanged()
      message.success('报告已保存修改。')
    } catch (saveError) {
      message.error(getApiErrorMessage(saveError))
    } finally {
      setSaving(false)
    }
  }

  const remove = async () => {
    if (!report) {
      return
    }
    setSaving(true)
    try {
      await reportApi.remove(report.id)
      onDataChanged()
      message.success('报告已删除。')
      onNavigate({ name: 'reports' })
    } catch (removeError) {
      message.error(getApiErrorMessage(removeError))
    } finally {
      setSaving(false)
    }
  }

  const exportMarkdown = async () => {
    if (!report) {
      return
    }
    try {
      await reportApi.downloadMarkdown(report)
      message.success('Markdown 已开始下载。')
    } catch (exportError) {
      message.error(getApiErrorMessage(exportError))
    }
  }

  const downloadExport = (reportId: string, format: 'docx' | 'pdf') => {
    const link = document.createElement('a')
    link.href = reportDownloadUrl(reportId, format)
    link.rel = 'noopener'
    document.body.appendChild(link)
    link.click()
    link.remove()
    message.success(format === 'docx' ? 'Word 文档已开始下载。' : 'PDF 已开始下载。')
  }

  if (loading && !report) {
    return (
      <div className="center-state page-state">
        <Spin size="large" />
        <p>正在展开报告…</p>
      </div>
    )
  }

  if (error && !report) {
    return (
      <div className="page-state">
        <InlineError message={error} onRetry={() => void load()} />
        <button
          className="paper-inline-button"
          type="button"
          onClick={() => onNavigate({ name: 'reports' })}
        >
          返回报告列表
        </button>
      </div>
    )
  }

  if (!report) {
    return null
  }

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow={`REPORT / ${REPORT_TYPE_LABELS[report.reportType]}`}
        title={report.title}
        description={`统计范围 ${formatDateTime(report.periodStart)} 至 ${formatDateTime(
          report.periodEnd,
        )}${report.projectName ? ` · 项目「${report.projectName}」` : ''}`}
        actions={
          <div className="hero-actions-row">
            <button
              className="paper-inline-button primary"
              type="button"
              onClick={() => void exportMarkdown()}
            >
              导出 Markdown
            </button>
            <button
              className="paper-inline-button"
              type="button"
              onClick={() => downloadExport(report.id, 'docx')}
            >
              导出 Word
            </button>
            <button
              className="paper-inline-button"
              type="button"
              onClick={() => downloadExport(report.id, 'pdf')}
            >
              导出 PDF
            </button>
            <button
              className="paper-inline-button"
              type="button"
              onClick={() => setEditing((current) => !current)}
            >
              {editing ? '取消编辑' : '编辑正文'}
            </button>
            <button
              className="paper-inline-button"
              type="button"
              disabled={saving}
              onClick={() => void remove()}
            >
              删除报告
            </button>
            <button
              className="paper-inline-button"
              type="button"
              onClick={() => onNavigate({ name: 'reports' })}
            >
              返回
            </button>
          </div>
        }
      />

      {error ? <InlineError message={error} onRetry={() => void load()} /> : null}

      <SectionCard
        no="01 /"
        title="报告正文"
        subtitle={report.aiUsed ? '含 AI 建议（客观统计由后端计算）' : '仅后端统计，未使用 AI 建议'}
      >
        {editing ? (
          <div className="report-editor">
            <textarea
              aria-label="报告正文"
              value={draftContent}
              rows={24}
              onChange={(event) => setDraftContent(event.target.value)}
            />
            <div className="action-actions">
              <button
                className="paper-inline-button primary"
                type="button"
                disabled={saving}
                onClick={() => void save()}
              >
                {saving ? '保存中…' : '保存修改'}
              </button>
              <button
                className="paper-inline-button"
                type="button"
                disabled={saving}
                onClick={() => {
                  setDraftContent(report.contentMd)
                  setEditing(false)
                }}
              >
                取消
              </button>
            </div>
          </div>
        ) : (
          <ReportContent content={report.contentMd} />
        )}
      </SectionCard>

      <SectionCard no="02 /" title="事实数据" subtitle="可追溯到真实任务与活动记录">
        <div className="facts-grid">
          <div>
            <dt>统计开始</dt>
            <dd>{formatDateTime(report.periodStart)}</dd>
          </div>
          <div>
            <dt>统计结束</dt>
            <dd>{formatDateTime(report.periodEnd)}</dd>
          </div>
          <div>
            <dt>报告类型</dt>
            <dd>{REPORT_TYPE_LABELS[report.reportType]}</dd>
          </div>
          <div>
            <dt>生成时间</dt>
            <dd>{formatDateTime(report.createdAt)}</dd>
          </div>
        </div>
      </SectionCard>
    </div>
  )
}

function ReportLab({
  projects,
  dataVersion,
  onDataChanged,
  onNavigate,
}: Omit<ReportsPageProps, 'reportId'>) {
  const { message } = App.useApp()
  const { reports, loading, error, reload, removeReport } = useReports(dataVersion)
  const [reportType, setReportType] = useState<ReportType>('daily')
  const [projectId, setProjectId] = useState<string>('')
  const [range, setRange] = useState<[Dayjs, Dayjs] | null>(null)
  const [generating, setGenerating] = useState(false)
  const [saving, setSaving] = useState(false)
  const [draft, setDraft] = useState<ReportDraft | null>(null)
  const [generateError, setGenerateError] = useState<string | null>(null)
  const [enhanced, setEnhanced] = useState(false)
  const [workTemplate, setWorkTemplate] = useState<'standard' | 'work'>('standard')

  const generate = async () => {
    if (reportType === 'project' && !projectId) {
      message.warning('项目报告需要先选择项目。')
      return
    }
    setGenerating(true)
    setGenerateError(null)
    try {
      const input = {
        reportType,
        projectId: reportType === 'project' ? projectId : null,
        periodStart: range ? range[0].toISOString() : null,
        periodEnd: range ? range[1].toISOString() : null,
      }
      const result = enhanced
        ? await reportApi.generateEnhanced({
            reportType,
            projectId: reportType === 'project' ? projectId : null,
            periodStart: toAppTimezone(
              range
                ? range[0]
                : reportType === 'daily'
                  ? dayjs()
                  : dayjs().subtract(6, 'day'),
            ).format('YYYY-MM-DD'),
            periodEnd: toAppTimezone(range ? range[1] : dayjs()).format('YYYY-MM-DD'),
            template: workTemplate,
          })
        : await reportApi.generate(input)
      setDraft(result)
    } catch (generateFailure) {
      setGenerateError(getApiErrorMessage(generateFailure))
    } finally {
      setGenerating(false)
    }
  }

  const saveDraft = async () => {
    if (!draft) {
      return
    }
    setSaving(true)
    try {
      const saved = await reportApi.save(draft)
      setDraft(null)
      onDataChanged()
      await reload()
      message.success('报告已保存。')
      onNavigate({ name: 'report', id: saved.id })
    } catch (saveError) {
      message.error(getApiErrorMessage(saveError))
    } finally {
      setSaving(false)
    }
  }

  const deleteSaved = async (reportId: string) => {
    try {
      await removeReport(reportId)
      onDataChanged()
      message.success('报告已删除。')
    } catch (deleteError) {
      message.error(getApiErrorMessage(deleteError))
    }
  }

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="REPORTS / 把做过的事收好"
        title={
          <>
            把这段时间，
            <br />
            <span className="marker">写成一张纸。</span>
          </>
        }
        description="统计由后端根据真实任务与活动记录计算；AI 只参与文字组织与建议。"
      />

      <div className="main-grid reports-grid">
        <SectionCard no="01 /" title="生成报告" subtitle="先选范围，再预览，确认后保存">
          <div className="report-form">
            <label className="sort-control full-width">
              <span className="sort-prefix">类型</span>
              <Select
                value={reportType}
                options={REPORT_TYPES}
                aria-label="报告类型"
                onChange={(value: ReportType) => {
                  setReportType(value)
                  setDraft(null)
                }}
              />
            </label>
            {reportType === 'project' ? (
              <label className="sort-control full-width">
                <span className="sort-prefix">项目</span>
                <Select
                  value={projectId || undefined}
                  placeholder="选择项目"
                  aria-label="报告项目"
                  options={projects.map((project) => ({
                    label: project.name,
                    value: project.id,
                  }))}
                  onChange={(value: string) => setProjectId(value)}
                />
              </label>
            ) : null}
            <label className="sort-control full-width">
              <span className="sort-prefix">时间范围</span>
              <DatePicker.RangePicker
                showTime={{ format: 'HH:mm' }}
                format="YYYY-MM-DD HH:mm"
                value={range}
                placeholder={['默认：今天/本周', '自动结束']}
                onChange={(values) =>
                  setRange(values && values[0] && values[1] ? [values[0], values[1]] : null)
                }
              />
            </label>
            <p className="muted-note">
              不选时间范围时：日报使用今天，周报使用本周，项目报告使用项目开始至今。
            </p>
            <label className="report-enhanced-toggle">
              <input
                type="checkbox"
                checked={enhanced}
                onChange={(event) => setEnhanced(event.target.checked)}
              />
              增强报告：包含专注时长、计划与实际对比、完成趋势与风险分析
            </label>
            {enhanced ? (
              <label className="sort-control full-width">
                <span className="sort-prefix">模板</span>
                <select
                  aria-label="报告模板"
                  value={workTemplate}
                  onChange={(event) =>
                    setWorkTemplate(event.target.value as 'standard' | 'work')
                  }
                >
                  <option value="standard">标准报告（统计 + 趋势）</option>
                  <option value="work">工作汇报（完成 / 未完成 / 明日计划 / 风险）</option>
                </select>
              </label>
            ) : null}
            <button
              className="paper-inline-button primary"
              type="button"
              disabled={generating}
              onClick={() => void generate()}
            >
              {generating ? '正在统计…' : enhanced ? '生成增强报告' : '生成报告草稿'}
            </button>
            {generateError ? <InlineError message={generateError} /> : null}
          </div>

          {draft ? (
            <div className="report-draft">
              <div className="report-draft-head">
                <strong>{draft.title}</strong>
                <span>
                  统计范围 {formatDateTime(draft.periodStart)} 至{' '}
                  {formatDateTime(draft.periodEnd)}
                  {draft.aiUsed ? ' · 含 AI 建议' : ' · 仅后端统计'}
                </span>
              </div>
              <div className="report-preview-box">
                <ReportContent content={draft.contentMd} />
              </div>
              <div className="action-actions">
                <button
                  className="paper-inline-button primary"
                  type="button"
                  disabled={saving}
                  onClick={() => void saveDraft()}
                >
                  {saving ? '保存中…' : '确认保存报告'}
                </button>
                <button
                  className="paper-inline-button"
                  type="button"
                  disabled={saving}
                  onClick={() => setDraft(null)}
                >
                  丢弃草稿
                </button>
              </div>
              <p className="action-result-note">未保存前不会写入报告记录。</p>
            </div>
          ) : (
            <EmptyState
              title="还没有生成报告"
              description="选择类型后生成草稿，预览确认后再保存。"
            />
          )}
        </SectionCard>

        <aside className="reports-aside">
          <SectionCard
            no="02 /"
            title="已保存报告"
            subtitle={`${reports.length} 份`}
            actions={
              <button className="paper-inline-button" type="button" onClick={() => void reload()}>
                刷新
              </button>
            }
          >
            {loading ? (
              <div className="center-state small">
                <Spin size="small" />
                <p>正在翻报告夹…</p>
              </div>
            ) : null}
            {error ? <InlineError message={error} onRetry={() => void reload()} /> : null}
            {!loading && reports.length === 0 ? (
              <p className="muted-note">还没有保存过报告。</p>
            ) : null}
            <ul className="report-list-cards">
              {reports.map((report) => (
                <li key={report.id}>
                  <button
                    className="report-list-title"
                    type="button"
                    onClick={() => onNavigate({ name: 'report', id: report.id })}
                  >
                    {report.title}
                  </button>
                  <small>
                    {REPORT_TYPE_LABELS[report.reportType]}
                    {report.projectName ? ` · ${report.projectName}` : ''} ·{' '}
                    {formatDateTime(report.createdAt)}
                  </small>
                  <div className="report-list-actions">
                    <button
                      className="task-action danger"
                      type="button"
                      aria-label={`删除报告 ${report.title}`}
                      onClick={() => void deleteSaved(report.id)}
                    >
                      删除
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </SectionCard>
        </aside>
      </div>
    </div>
  )
}

export function ReportsPage({
  reportId,
  projects,
  dataVersion,
  onDataChanged,
  onNavigate,
}: ReportsPageProps) {
  if (reportId) {
    return (
      <ReportDetailView
        reportId={reportId}
        onNavigate={onNavigate}
        onDataChanged={onDataChanged}
      />
    )
  }
  return (
    <ReportLab
      projects={projects}
      dataVersion={dataVersion}
      onDataChanged={onDataChanged}
      onNavigate={onNavigate}
    />
  )
}
