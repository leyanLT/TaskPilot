import { App, Spin } from 'antd'
import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { useAssistant, type ChatMessage } from '../hooks/useAssistant'
import {
  toBreakdownOverrides,
  toPlanOverrides,
  toReportOverrides,
} from '../services/assistant'
import type {
  ActionStatus,
  ActionType,
  BreakdownDraft,
  PendingAction,
  PlanDraft,
  Project,
  ReportDraft,
  TaskCandidate,
  TaskDraft,
} from '../types'
import { useSpeechInput } from '../hooks/useSpeechInput'
import { formatDateTime } from '../utils/datetime'
import { BreakdownEditor, PlanDraftCard, ReportDraftCard } from './ActionDrafts'
import { DoodleWorker } from './DoodleWorker'

const QUICK_PROMPTS = [
  '帮我安排今天',
  '我今天有 5 小时，帮我安排今天的任务',
  '我需要在两周内完成一个 AI Agent 项目，帮我拆解任务',
  '帮我生成这周的工作周报',
  '给待办任务排个优先级',
  '回顾一下这周',
]

const ACTION_LABEL: Record<ActionType, string> = {
  create_task: '创建任务',
  create_tasks: '批量草稿',
  complete_task: '标记完成',
  update_task: '修改任务',
  delete_task: '删除任务',
  batch_reschedule: '批量改期',
  create_task_breakdown: '任务拆解',
  save_daily_plan: '今日计划',
  save_report: '保存报告',
  apply_replan: '重排计划',
  create_project: '创建项目',
}

const CONFIRM_LABEL: Record<ActionType, string> = {
  create_task: '确认创建',
  create_tasks: '确认创建',
  complete_task: '确认完成',
  update_task: '确认修改',
  delete_task: '确认删除',
  batch_reschedule: '确认改期',
  create_task_breakdown: '确认创建',
  save_daily_plan: '确认保存',
  save_report: '确认保存',
  apply_replan: '确认重排',
  create_project: '确认创建',
}

const SUCCESS_TEXT: Record<ActionType, string> = {
  create_task: '任务已创建。',
  create_tasks: '任务草稿已创建。',
  complete_task: '任务已标记完成。',
  update_task: '任务已更新。',
  delete_task: '任务已删除。',
  batch_reschedule: '任务已批量改期。',
  create_task_breakdown: '任务拆解已创建。',
  save_daily_plan: '今日计划已保存。',
  save_report: '报告已保存。',
  apply_replan: '计划已按新方案重排。',
  create_project: '项目已创建。',
}

const STATUS_LABEL: Record<ActionStatus, { tone: string; text: string }> = {
  pending: { tone: 'pending', text: '待确认' },
  processing: { tone: 'processing', text: '执行中' },
  confirmed: { tone: 'confirmed', text: '已确认执行' },
  cancelled: { tone: 'cancelled', text: '已取消' },
  expired: { tone: 'expired', text: '已过期' },
}

interface AssistantPanelProps {
  onTasksChanged: () => Promise<unknown> | void
  projects?: Project[]
  onOpenReport?: (reportId: string) => void
}

type ConfirmDraft = BreakdownDraft | PlanDraft | ReportDraft

interface ActionCardProps {
  action: PendingAction
  busy: boolean
  disabled: boolean
  projects: Project[]
  onConfirm: (action: PendingAction, confirm: boolean) => Promise<void>
  onConfirmDraft: (action: PendingAction, draft: ConfirmDraft) => Promise<void>
}

function dueText(value: string | null): string {
  return value ? `截止 ${formatDateTime(value)}` : '未设置截止时间'
}

function singleTask(action: PendingAction): TaskDraft | null {
  if (action.proposedTask) {
    return action.proposedTask
  }
  if (action.targetTask) {
    return {
      title: action.targetTask.title,
      description: action.targetTask.description,
      dueAt: action.targetTask.dueAt,
      priority: action.targetTask.priority,
      estimatedMinutes: action.targetTask.estimatedMinutes,
      projectId: action.targetTask.projectId,
    }
  }
  return null
}

function ActionCard({
  action,
  busy,
  disabled,
  projects,
  onConfirm,
  onConfirmDraft,
}: ActionCardProps) {
  const status = STATUS_LABEL[action.status]
  const task = singleTask(action)
  const isDraftList = action.actionType === 'create_tasks'
  const isBatch = action.actionType === 'batch_reschedule'
  const isBreakdown =
    action.actionType === 'create_task_breakdown' && action.proposedBreakdown
  const isPlan = action.actionType === 'save_daily_plan' && action.proposedPlan
  const isReport = action.actionType === 'save_report' && action.proposedReport
  const isDraft = Boolean(isBreakdown || isPlan || isReport)
  const changedFields = new Set(action.changes?.changedFields ?? [])

  const title = isDraftList
    ? `${action.proposedTasks.length} 个任务草稿`
    : isBatch
      ? `${action.targetTasks.length} 个任务统一改期`
      : isBreakdown && action.proposedBreakdown
        ? action.proposedBreakdown.goal
        : isPlan && action.proposedPlan
          ? `${action.proposedPlan.planDate} 的今日计划`
          : isReport && action.proposedReport
            ? action.proposedReport.title
            : (task?.title ?? action.summary)

  return (
    <div className={`action-card action-card-${action.actionType}`}>
      <div className="action-card-top">
        <span className="action-label">待确认操作</span>
        <span className="action-kind">{ACTION_LABEL[action.actionType]}</span>
        <span className={`action-status action-status-${status.tone}`}>{status.text}</span>
      </div>
      <strong className="action-title">{title}</strong>

      {isDraftList ? (
        <ul className="action-task-list">
          {action.proposedTasks.map((draft, index) => (
            <li key={`${draft.title}-${index}`}>
              <span>{draft.title}</span>
              <small>{dueText(draft.dueAt)}</small>
            </li>
          ))}
        </ul>
      ) : null}

      {isBatch ? (
        <>
          <p className="action-due">{action.summary}</p>
          <ul className="action-task-list">
            {action.targetTasks.slice(0, 6).map((target) => (
              <li key={target.id}>
                <span>{target.title}</span>
                <small>{dueText(target.dueAt)}</small>
              </li>
            ))}
            {action.targetTasks.length > 6 ? (
              <li className="action-list-more">等 {action.targetTasks.length} 个任务</li>
            ) : null}
          </ul>
        </>
      ) : null}

      {isBreakdown && action.proposedBreakdown && action.status === 'pending' ? (
        <BreakdownEditor
          breakdown={action.proposedBreakdown}
          projects={projects}
          busy={busy || disabled}
          onConfirm={(draft) => void onConfirmDraft(action, draft)}
          onCancel={() => void onConfirm(action, false)}
        />
      ) : null}

      {isPlan && action.proposedPlan && action.status === 'pending' ? (
        <PlanDraftCard
          plan={action.proposedPlan}
          busy={busy || disabled}
          onConfirm={(draft) => void onConfirmDraft(action, draft)}
          onCancel={() => void onConfirm(action, false)}
        />
      ) : null}

      {isReport && action.proposedReport && action.status === 'pending' ? (
        <ReportDraftCard
          report={action.proposedReport}
          busy={busy || disabled}
          onConfirm={() =>
            void onConfirmDraft(action, action.proposedReport as ReportDraft)
          }
          onCancel={() => void onConfirm(action, false)}
        />
      ) : null}

      {!isDraft && !isDraftList && !isBatch && task?.description ? (
        <p className="action-description">{task.description}</p>
      ) : null}

      {action.actionType === 'update_task' && action.changes ? (
        <div className="action-change-list">
          {changedFields.has('title') ? (
            <p>
              <span>标题</span>
              <s>{action.targetTask?.title ?? '原任务'}</s>
              <b>{action.changes.title}</b>
            </p>
          ) : null}
          {changedFields.has('due_at') ? (
            <p>
              <span>截止时间</span>
              <b>{action.changes.dueAt ? formatDateTime(action.changes.dueAt) : '取消截止时间'}</b>
            </p>
          ) : null}
          {changedFields.has('priority') ? (
            <p>
              <span>优先级</span>
              <b>
                {action.changes.priority === 'high'
                  ? '高'
                  : action.changes.priority === 'low'
                    ? '弱'
                    : '中'}
              </b>
            </p>
          ) : null}
          {changedFields.has('estimated_minutes') ? (
            <p>
              <span>预计耗时</span>
              <b>
                {action.changes.estimatedMinutes
                  ? `${action.changes.estimatedMinutes} 分钟`
                  : '清空'}
              </b>
            </p>
          ) : null}
          {changedFields.has('project_id') ? (
            <p>
              <span>所属项目</span>
              <b>{action.changes.projectName ?? '移出项目'}</b>
            </p>
          ) : null}
          {changedFields.has('description') ? (
            <p>
              <span>描述</span>
              <b>{action.changes.description ? '已更新' : '已清空'}</b>
            </p>
          ) : null}
        </div>
      ) : null}

      {!isDraft && !isDraftList && !isBatch && !changedFields.has('due_at') ? (
        <p className="action-due">{dueText(task?.dueAt ?? null)}</p>
      ) : null}

      {action.actionType === 'delete_task' ? (
        <p className="action-danger-note">删除后无法恢复，请确认不是误操作。</p>
      ) : null}

      {action.status === 'pending' && !isDraft ? (
        <div className="action-actions">
          <button
            className={`paper-inline-button primary ${
              action.actionType === 'delete_task' ? 'danger' : ''
            }`}
            type="button"
            disabled={disabled || busy}
            onClick={() => void onConfirm(action, true)}
          >
            {busy ? '正在执行…' : CONFIRM_LABEL[action.actionType]}
          </button>
          <button
            className="paper-inline-button"
            type="button"
            disabled={disabled || busy}
            onClick={() => void onConfirm(action, false)}
          >
            取消操作
          </button>
        </div>
      ) : null}

      {action.status !== 'pending' ? (
        <p className="action-result-note">
          {action.status === 'confirmed'
            ? '此操作已经执行。'
            : action.status === 'expired'
              ? '此操作已过期，请重新发起。'
              : '此操作未执行，任务数据未被修改。'}
        </p>
      ) : null}
    </div>
  )
}

interface CandidateListProps {
  message: ChatMessage
  disabled: boolean
  onSelect: (sourceMessageId: string, candidate: TaskCandidate) => void
}

function CandidateList({ message, disabled, onSelect }: CandidateListProps) {
  if (!message.candidates?.length) {
    return null
  }
  return (
    <div className="candidate-list">
      <p className="candidate-label">请明确选择一个任务：</p>
      {message.candidates.map((candidate) => (
        <button
          key={candidate.id}
          className="candidate-button"
          type="button"
          disabled={disabled}
          onClick={() => onSelect(message.id, candidate)}
        >
          <span className="candidate-title">{candidate.title}</span>
          <span className="candidate-due">
            {candidate.dueAt ? formatDateTime(candidate.dueAt) : '无截止时间'}
          </span>
        </button>
      ))}
    </div>
  )
}

function WelcomeMessage() {
  return (
    <div className="chat-message chat-assistant chat-welcome">
      <span className="chat-mark" aria-hidden="true">
        <i />
        <i />
      </span>
      <div className="chat-bubble">
        <div className="chat-content">
          你好，我是 TaskPilot AI 助手。你可以让我查询任务与项目、拆解目标、安排今天、
          调整优先级、生成日报或周报。所有写操作都会先停在下方，等你确认。
        </div>
      </div>
    </div>
  )
}

export function AssistantPanel({
  onTasksChanged,
  projects = [],
  onOpenReport,
}: AssistantPanelProps) {
  const { message } = App.useApp()
  const [input, setInput] = useState('')
  const speech = useSpeechInput((text) => {
    setInput((current) => (current.trim() ? `${current} ${text}` : text))
  })
  const messagesContainerRef = useRef<HTMLDivElement | null>(null)
  const {
    messages,
    loading,
    historyLoading,
    actionBusyId,
    error,
    sendMessage,
    selectCandidate,
    confirmAction,
    retryHistory,
  } = useAssistant({ onTasksChanged })

  const hasStreamingMessage = messages.some((item) => item.streaming)
  const showEmptyState = !historyLoading && messages.length === 0

  useEffect(() => {
    const node = messagesContainerRef.current
    if (node) {
      node.scrollTop = node.scrollHeight
    }
  }, [messages, loading, historyLoading])

  const submitInput = async () => {
    const text = input.trim()
    if (!text || loading || historyLoading) {
      return
    }
    setInput('')
    await sendMessage(text)
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      void submitInput()
    }
  }

  const handleConfirm = async (action: PendingAction, confirm: boolean) => {
    const result = await confirmAction(action.id, confirm)
    if (!result) {
      return
    }
    if (result.status === 'confirmed') {
      message.success(SUCCESS_TEXT[action.actionType])
    } else if (result.status === 'cancelled') {
      message.info('操作已取消，未修改任务。')
    }
  }

  const handleConfirmDraft = async (action: PendingAction, draft: ConfirmDraft) => {
    let overrides: Record<string, unknown>
    if (action.actionType === 'create_task_breakdown') {
      overrides = toBreakdownOverrides(draft as BreakdownDraft)
    } else if (action.actionType === 'save_daily_plan') {
      overrides = toPlanOverrides(draft as PlanDraft)
    } else {
      overrides = toReportOverrides(draft as ReportDraft)
    }
    const result = await confirmAction(action.id, true, overrides)
    if (!result) {
      return
    }
    if (result.status === 'confirmed') {
      message.success(SUCCESS_TEXT[action.actionType])
      if (result.reportId && onOpenReport) {
        onOpenReport(result.reportId)
      }
    }
  }

  const handleCandidateSelect = async (
    sourceMessageId: string,
    candidate: TaskCandidate,
  ) => {
    const succeeded = await selectCandidate(sourceMessageId, candidate)
    if (!succeeded) {
      message.error('选择任务失败，请重试。')
    }
  }

  return (
    <section className="assistant-panel" id="assistant-panel" aria-label="AI 助手">
      <div className="assistant-tape" aria-hidden="true" />
      <header className="assistant-header">
        <DoodleWorker className="assistant-doodle" />
        <div className="assistant-heading">
          <h2>小帮手</h2>
          <p>AI 助手 · DeepSeek · 写操作需确认</p>
        </div>
        <span className="assistant-online">在线</span>
      </header>

      <div className="chat-messages" aria-live="polite" ref={messagesContainerRef}>
        {historyLoading ? (
          <div className="chat-history-state">
            <Spin size="small" />
            <span>正在翻上次的对话…</span>
          </div>
        ) : null}

        {showEmptyState && error ? (
          <div className="chat-history-state chat-history-error">
            <span>{error}</span>
            <button
              className="paper-inline-button"
              type="button"
              onClick={() => void retryHistory()}
            >
              重新加载对话
            </button>
          </div>
        ) : null}

        {showEmptyState && !error ? <WelcomeMessage /> : null}

        {messages.map((chatMessage) => (
          <div
            key={chatMessage.id}
            className={`chat-message chat-${chatMessage.role} ${
              chatMessage.isError ? 'chat-error' : ''
            } ${chatMessage.streaming ? 'chat-streaming' : ''}`}
          >
            {chatMessage.role === 'assistant' ? (
              <span className="chat-mark" aria-hidden="true">
                <i />
                <i />
              </span>
            ) : null}
            <div className="chat-bubble">
              <div className="chat-content">
                {chatMessage.content}
                {chatMessage.streaming && chatMessage.content ? (
                  <span className="stream-cursor" aria-hidden="true" />
                ) : null}
                {chatMessage.streaming && !chatMessage.content ? (
                  <span className="chat-stream-status">
                    <Spin size="small" />
                    {chatMessage.streamStatus ?? 'AI 正在处理…'}
                  </span>
                ) : null}
              </div>
              {chatMessage.action ? (
                <ActionCard
                  action={chatMessage.action}
                  busy={actionBusyId === chatMessage.action.id}
                  disabled={actionBusyId !== null}
                  projects={projects}
                  onConfirm={handleConfirm}
                  onConfirmDraft={handleConfirmDraft}
                />
              ) : null}
              {chatMessage.candidates ? (
                <CandidateList
                  message={chatMessage}
                  disabled={loading}
                  onSelect={(sourceId, candidate) =>
                    void handleCandidateSelect(sourceId, candidate)
                  }
                />
              ) : null}
            </div>
          </div>
        ))}

        {loading && !hasStreamingMessage ? (
          <div className="chat-message chat-assistant">
            <span className="chat-mark" aria-hidden="true">
              <i />
              <i />
            </span>
            <div className="chat-bubble chat-thinking">
              <Spin size="small" /> <span>AI 正在处理…</span>
            </div>
          </div>
        ) : null}

        {showEmptyState && !error ? (
          <>
            <div className="quick-prompts">
              {QUICK_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  className="prompt-chip"
                  type="button"
                  onClick={() => {
                    setInput('')
                    void sendMessage(prompt)
                  }}
                >
                  {prompt}
                </button>
              ))}
            </div>
            <div className="assistant-idle">
              <span className="idle-rule" aria-hidden="true" />
              <p>写下的事，不必一次都做完。</p>
              <span>所有写操作都先停在这里，等你点头。</span>
              <svg viewBox="0 0 74 24" fill="none" aria-hidden="true">
                <path
                  d="M3 16c14-8 32-11 52-8 7 1 12 3 16 7"
                  stroke="currentColor"
                  strokeWidth="1.2"
                  strokeLinecap="round"
                />
                <path
                  d="m64 12 7 3-5 6"
                  stroke="currentColor"
                  strokeWidth="1.2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </div>
          </>
        ) : null}
      </div>

      <div className="assistant-composer">
        <textarea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="和我说说今天，或问问待办…"
          maxLength={2000}
          rows={2}
          disabled={loading || historyLoading}
          aria-label="给 AI 助手发送消息"
        />
        {speech.listening ? (
          <p className="voice-interim">{speech.interim || '正在听…'}</p>
        ) : null}
        <div className="composer-footer">
          <span className="composer-hint">
            Enter 发送 · Shift + Enter 换行 · 可语音输入
          </span>
          <button
            className={`voice-button ${speech.listening ? 'is-listening' : ''}`}
            type="button"
            aria-label={
              speech.supported
                ? speech.listening
                  ? '停止语音输入'
                  : '语音输入'
                : '当前浏览器不支持语音输入'
            }
            title={
              speech.supported
                ? '语音输入（普通话），识别由浏览器完成'
                : '当前浏览器不支持语音输入，请使用 Chrome 或 Edge'
            }
            disabled={!speech.supported || loading || historyLoading}
            onClick={speech.toggle}
          >
            <span aria-hidden="true">{speech.listening ? '◉' : '🎙'}</span>
            {speech.listening ? '停止' : '语音'}
          </button>
          <button
            className="send-button"
            type="button"
            disabled={loading || historyLoading || !input.trim()}
            onClick={() => void submitInput()}
          >
            {loading ? '处理中' : '发送'}
            <span aria-hidden="true">↗</span>
          </button>
        </div>
      </div>
      <p className="assistant-foot">不替你擅自改动任务 · 每次写入都等你点头</p>
    </section>
  )
}
