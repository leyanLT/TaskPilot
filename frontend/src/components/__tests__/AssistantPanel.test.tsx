import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AssistantPanel } from '../AssistantPanel'
import { assistantApi } from '../../services/assistant'
import { renderWithApp } from '../../test/render'
import {
  makeAction,
  makeAssistantMessage,
  makeAssistantTurn,
  makeCandidate,
  makeTask,
} from '../../test/fixtures'
import type { AssistantStreamEvent } from '../../types'

vi.mock('../../services/assistant', () => ({
  assistantApi: {
    history: vi.fn(),
    streamMessage: vi.fn(),
    sendMessage: vi.fn(),
    confirm: vi.fn(),
  },
}))

const mockedHistory = vi.mocked(assistantApi.history)
const mockedStream = vi.mocked(assistantApi.streamMessage)
const mockedSend = vi.mocked(assistantApi.sendMessage)
const mockedConfirm = vi.mocked(assistantApi.confirm)

function streamEvents(events: AssistantStreamEvent[]) {
  return (async function* generate(): AsyncGenerator<AssistantStreamEvent> {
    for (const event of events) {
      yield event
    }
  })()
}

function startedEvent(content: string): AssistantStreamEvent {
  return {
    type: 'started',
    userMessage: makeAssistantMessage({
      id: 'persisted-user',
      role: 'user',
      content,
      promptVersion: null,
    }),
    promptVersion: '2026-11-v4',
  }
}

function doneEvent(
  content: string,
  overrides: Parameters<typeof makeAssistantMessage>[0] = {},
): AssistantStreamEvent {
  return {
    type: 'done',
    assistantMessage: makeAssistantMessage({ content, ...overrides }),
  }
}

async function renderPanel(onTasksChanged = vi.fn()) {
  renderWithApp(<AssistantPanel onTasksChanged={onTasksChanged} />)
  await waitFor(() => {
    expect(screen.getByLabelText('给 AI 助手发送消息')).toBeEnabled()
  })
  return onTasksChanged
}

async function sendText(text: string) {
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('给 AI 助手发送消息'), text)
  await user.click(screen.getByRole('button', { name: '发送' }))
  return user
}

describe('AssistantPanel', () => {
  beforeEach(() => {
    mockedHistory.mockReset()
    mockedStream.mockReset()
    mockedSend.mockReset()
    mockedConfirm.mockReset()
    mockedHistory.mockResolvedValue([])
  })

  it('loads persisted history and renders it without the welcome state', async () => {
    mockedHistory.mockResolvedValue([
      makeAssistantMessage({
        id: 'history-user',
        role: 'user',
        content: '上次问的问题',
        promptVersion: null,
      }),
      makeAssistantMessage({ id: 'history-assistant', content: '上次的回复' }),
    ])
    await renderPanel()

    expect(screen.getByText('上次问的问题')).toBeInTheDocument()
    expect(screen.getByText('上次的回复')).toBeInTheDocument()
    expect(screen.queryByText('帮我安排今天')).not.toBeInTheDocument()
    expect(screen.queryByText('写下的事，不必一次都做完。')).not.toBeInTheDocument()
  })

  it('streams a natural-language reply and persists the final message', async () => {
    mockedStream.mockReturnValue(
      streamEvents([
        startedEvent('我还有哪些任务没有完成？'),
        { type: 'status', phase: 'using_tools' },
        { type: 'token', delta: '你有 1 个' },
        { type: 'token', delta: '待完成的任务。' },
        doneEvent('你有 1 个待完成的任务。'),
      ]),
    )
    await renderPanel()

    await sendText('我还有哪些任务没有完成？')

    expect(await screen.findByText('你有 1 个待完成的任务。')).toBeInTheDocument()
    expect(mockedStream).toHaveBeenCalledWith(
      '我还有哪些任务没有完成？',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it('shows token content before the done event', async () => {
    let release: () => void = () => undefined
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    mockedStream.mockReturnValue(
      (async function* generate(): AsyncGenerator<AssistantStreamEvent> {
        yield startedEvent('查询任务')
        yield { type: 'token', delta: '先流出来的' }
        await gate
        yield doneEvent('先流出来的完整回复')
      })(),
    )
    await renderPanel()

    await sendText('查询任务')
    expect(await screen.findByText('先流出来的')).toBeInTheDocument()

    release()
    expect(await screen.findByText('先流出来的完整回复')).toBeInTheDocument()
  })

  it('shows a create draft and only writes after confirmation', async () => {
    const action = makeAction({ summary: '创建任务「新任务」' })
    mockedStream.mockReturnValue(
      streamEvents([
        startedEvent('明天下午三点创建新任务'),
        doneEvent('创建任务「新任务」。请在下方确认后执行。', { action }),
      ]),
    )
    mockedConfirm.mockResolvedValue({
      actionId: action.id,
      status: 'confirmed',
      message: '任务已创建。',
      task: makeTask({ id: 'new-task', title: '新任务' }),
      affectedTasks: [],
      reportId: null,
      planDate: null,
    })
    const onTasksChanged = await renderPanel()

    const user = await sendText('明天下午三点创建新任务')

    expect(await screen.findByText('待确认操作')).toBeInTheDocument()
    expect(mockedConfirm).not.toHaveBeenCalled()
    expect(onTasksChanged).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: '确认创建' }))

    await waitFor(() => {
      expect(mockedConfirm).toHaveBeenCalledWith(action.id, true)
      expect(onTasksChanged).toHaveBeenCalledTimes(1)
    })
    expect(await screen.findByText('此操作已经执行。')).toBeInTheDocument()
  })

  it('cancels a pending action without changing tasks', async () => {
    const action = makeAction({ actionType: 'complete_task' })
    mockedStream.mockReturnValue(
      streamEvents([
        startedEvent('把任务标记为完成'),
        doneEvent('将任务标记为已完成。请在下方确认后执行。', { action }),
      ]),
    )
    mockedConfirm.mockResolvedValue({
      actionId: action.id,
      status: 'cancelled',
      message: '操作已取消，未修改任何任务。',
      task: null,
      affectedTasks: [],
      reportId: null,
      planDate: null,
    })
    const onTasksChanged = await renderPanel()

    const user = await sendText('把任务标记为完成')
    await user.click(await screen.findByRole('button', { name: '取消操作' }))

    await waitFor(() => {
      expect(mockedConfirm).toHaveBeenCalledWith(action.id, false)
    })
    expect(onTasksChanged).not.toHaveBeenCalled()
    expect(await screen.findByText('此操作未执行，任务数据未被修改。')).toBeInTheDocument()
  })

  it('sends source_message_id when selecting a persisted candidate', async () => {
    const first = makeCandidate({ id: 'candidate-a', title: '实验报告 A' })
    const second = makeCandidate({ id: 'candidate-b', title: '实验报告 B' })
    mockedHistory.mockResolvedValue([
      makeAssistantMessage({
        id: 'ambiguous-message',
        content: '找到 2 个匹配任务，请明确选择。',
        candidates: [first, second],
      }),
    ])
    const action = makeAction({
      summary: '将任务「实验报告 A」标记为已完成',
      actionType: 'complete_task',
    })
    mockedSend.mockResolvedValue(
      makeAssistantTurn({
        userMessage: makeAssistantMessage({
          id: 'selection-user',
          role: 'user',
          content: '选择任务「实验报告 A」',
          promptVersion: null,
        }),
        assistantMessage: makeAssistantMessage({
          id: 'selection-assistant',
          content: '将任务「实验报告 A」标记为已完成。请在下方确认后执行。',
          action,
        }),
      }),
    )
    await renderPanel()

    const candidateButtons = await screen.findAllByRole('button', {
      name: /实验报告/,
    })
    expect(candidateButtons).toHaveLength(2)
    await userEvent.setup().click(candidateButtons[0])

    await waitFor(() => {
      expect(mockedSend).toHaveBeenLastCalledWith('选择任务「实验报告 A」', {
        selectedTaskId: 'candidate-a',
        sourceMessageId: 'ambiguous-message',
      })
    })
    expect(await screen.findByText('待确认操作')).toBeInTheDocument()
  })

  it('displays a safe stream error without crashing the page', async () => {
    mockedStream.mockReturnValue(
      streamEvents([
        startedEvent('查询任务'),
        {
          type: 'error',
          code: 'AI_UNAVAILABLE',
          message: 'AI 服务暂时不可用，请稍后重试。',
        },
      ]),
    )
    await renderPanel()

    await sendText('查询任务')

    expect(
      await screen.findByText('AI 服务暂时不可用，请稍后重试。'),
    ).toBeInTheDocument()
    expect(screen.getByLabelText('给 AI 助手发送消息')).toBeEnabled()
  })

  it('shows a loading state while the stream is waiting for a response', async () => {
    let release: () => void = () => undefined
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    mockedStream.mockReturnValue(
      (async function* generate(): AsyncGenerator<AssistantStreamEvent> {
        yield startedEvent('查询任务')
        await gate
        yield doneEvent('查询完成。')
      })(),
    )
    await renderPanel()

    await sendText('查询任务')

    expect(await screen.findByText('AI 正在翻任务…')).toBeInTheDocument()
    expect(screen.getByLabelText('给 AI 助手发送消息')).toBeDisabled()

    release()
    expect(await screen.findByText('查询完成。')).toBeInTheDocument()
    expect(screen.getByLabelText('给 AI 助手发送消息')).toBeEnabled()
  })

  it('renders a persisted update action with before/after changes', async () => {
    const action = makeAction({
      actionType: 'update_task',
      summary: '修改任务「旧标题」：标题改为「新标题」',
      proposedTask: null,
      targetTask: makeTask({ id: 'update-task', title: '旧标题' }),
      changes: {
        title: '新标题',
        description: null,
        dueAt: '2999-02-01T10:00:00+00:00',
        priority: null,
        estimatedMinutes: null,
        projectId: null,
        projectName: null,
        changedFields: ['title', 'due_at'],
      },
    })
    mockedHistory.mockResolvedValue([
      makeAssistantMessage({
        id: 'update-message',
        content: action.summary,
        action,
      }),
    ])
    await renderPanel()

    expect(screen.getByText('修改任务')).toBeInTheDocument()
    expect(screen.getAllByText('旧标题').length).toBeGreaterThan(0)
    expect(screen.getByText('新标题')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '确认修改' })).toBeInTheDocument()
  })

  it('renders a persisted delete action with a destructive confirmation', async () => {
    const action = makeAction({
      actionType: 'delete_task',
      summary: '删除任务「旧任务」',
      proposedTask: null,
      targetTask: makeTask({ id: 'delete-task', title: '旧任务' }),
    })
    mockedHistory.mockResolvedValue([
      makeAssistantMessage({ id: 'delete-message', content: action.summary, action }),
    ])
    await renderPanel()

    expect(screen.getByText('删除任务')).toBeInTheDocument()
    expect(screen.getByText('删除后无法恢复，请确认不是误操作。')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '确认删除' })).toBeInTheDocument()
  })

  it('renders a batch reschedule action with every affected task', async () => {
    const action = makeAction({
      actionType: 'batch_reschedule',
      summary: '将 2 个任务的截止时间调整为 11月07日 18:00',
      proposedTask: null,
      targetTasks: [
        makeTask({ id: 'batch-1', title: '批量一' }),
        makeTask({ id: 'batch-2', title: '批量二' }),
      ],
    })
    mockedHistory.mockResolvedValue([
      makeAssistantMessage({ id: 'batch-message', content: action.summary, action }),
    ])
    await renderPanel()

    expect(screen.getByText('2 个任务统一改期')).toBeInTheDocument()
    expect(screen.getByText('批量一')).toBeInTheDocument()
    expect(screen.getByText('批量二')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '确认改期' })).toBeInTheDocument()
  })

  it('retries a failed history load', async () => {
    mockedHistory
      .mockRejectedValueOnce(new Error('历史读取失败。'))
      .mockResolvedValueOnce([])
    renderWithApp(<AssistantPanel onTasksChanged={vi.fn()} />)

    expect(await screen.findByText('历史读取失败。')).toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: '重新加载对话' }))

    expect(await screen.findByText('帮我安排今天')).toBeInTheDocument()
  })
})
