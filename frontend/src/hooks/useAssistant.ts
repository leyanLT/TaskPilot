import { useCallback, useEffect, useRef, useState } from 'react'
import { assistantApi } from '../services/assistant'
import { ApiError, getApiErrorMessage } from '../services/http'
import type {
  AssistantChatMessage,
  AssistantMessage,
  TaskCandidate,
} from '../types'

export type ChatMessage = AssistantChatMessage

let messageSequence = 0

function nextMessageId(prefix = 'message'): string {
  messageSequence += 1
  return `${prefix}-${Date.now()}-${messageSequence}`
}

function toChatMessage(message: AssistantMessage): ChatMessage {
  return { ...message }
}

const STREAM_LABELS = {
  thinking: 'AI 正在翻任务…',
  using_tools: '正在读取真实任务…',
  preparing_action: '正在整理待确认操作…',
  composing: '正在写回复…',
} as const

interface UseAssistantOptions {
  onTasksChanged: () => Promise<unknown> | void
}

export function useAssistant({ onTasksChanged }: UseAssistantOptions) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [loading, setLoading] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(true)
  const [actionBusyId, setActionBusyId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const busyRef = useRef(false)
  const controllerRef = useRef<AbortController | null>(null)

  const loadHistory = useCallback(async () => {
    try {
      const history = await assistantApi.history()
      setMessages(history.map(toChatMessage))
    } catch (loadError) {
      setError(getApiErrorMessage(loadError))
    } finally {
      setHistoryLoading(false)
    }
  }, [])

  const retryHistory = useCallback(async () => {
    setHistoryLoading(true)
    setError(null)
    await loadHistory()
  }, [loadHistory])

  useEffect(() => {
    let active = true
    assistantApi
      .history()
      .then((history) => {
        if (active) {
          setMessages(history.map(toChatMessage))
        }
      })
      .catch((loadError: unknown) => {
        if (active) {
          setError(getApiErrorMessage(loadError))
        }
      })
      .finally(() => {
        if (active) {
          setHistoryLoading(false)
        }
      })
    return () => {
      active = false
      controllerRef.current?.abort()
    }
  }, [])

  const appendError = useCallback((messageText: string) => {
    setError(messageText)
    setMessages((current) => [
      ...current,
      {
        id: nextMessageId('error'),
        role: 'assistant',
        content: messageText,
        action: null,
        candidates: [],
        promptVersion: null,
        createdAt: new Date().toISOString(),
        isError: true,
      },
    ])
  }, [])

  const sendMessage = useCallback(
    async (rawMessage: string): Promise<boolean> => {
      const text = rawMessage.trim()
      if (!text || busyRef.current) {
        return false
      }
      busyRef.current = true
      setLoading(true)
      setError(null)

      const tempUserId = nextMessageId('temp-user')
      const tempAssistantId = nextMessageId('temp-assistant')
      setMessages((current) => [
        ...current,
        {
          id: tempUserId,
          role: 'user',
          content: text,
          action: null,
          candidates: [],
          promptVersion: null,
          createdAt: new Date().toISOString(),
        },
        {
          id: tempAssistantId,
          role: 'assistant',
          content: '',
          action: null,
          candidates: [],
          promptVersion: null,
          createdAt: new Date().toISOString(),
          streaming: true,
          streamStatus: STREAM_LABELS.thinking,
        },
      ])

      const controller = new AbortController()
      controllerRef.current = controller
      let timedOut = false
      const timeout = window.setTimeout(() => {
        timedOut = true
        controller.abort()
      }, 120_000)
      let terminal = false

      try {
        for await (const event of assistantApi.streamMessage(text, {
          signal: controller.signal,
        })) {
          if (event.type === 'started') {
            setMessages((current) =>
              current.map((message) =>
                message.id === tempUserId
                  ? toChatMessage(event.userMessage)
                  : message,
              ),
            )
          } else if (event.type === 'status') {
            setMessages((current) =>
              current.map((message) =>
                message.id === tempAssistantId
                  ? {
                      ...message,
                      streaming: true,
                      streamStatus: STREAM_LABELS[event.phase],
                    }
                  : message,
              ),
            )
          } else if (event.type === 'token') {
            setMessages((current) =>
              current.map((message) =>
                message.id === tempAssistantId
                  ? {
                      ...message,
                      content: message.content + event.delta,
                      streaming: true,
                      streamStatus: undefined,
                    }
                  : message,
              ),
            )
          } else if (event.type === 'done') {
            terminal = true
            setMessages((current) =>
              current.map((message) =>
                message.id === tempAssistantId
                  ? toChatMessage(event.assistantMessage)
                  : message,
              ),
            )
          } else if (event.type === 'error') {
            terminal = true
            setMessages((current) =>
              current.filter((message) => message.id !== tempAssistantId),
            )
            appendError(event.message)
            return false
          }
        }

        if (!terminal) {
          setMessages((current) =>
            current.filter((message) => message.id !== tempAssistantId),
          )
          appendError('AI 回复意外中断，请重试。')
          return false
        }
        return true
      } catch (streamError) {
        setMessages((current) =>
          current.filter((message) => message.id !== tempAssistantId),
        )
        const messageText = timedOut
          ? 'AI 请求超时，请稍后重试。'
          : getApiErrorMessage(streamError)
        appendError(messageText)
        return false
      } finally {
        window.clearTimeout(timeout)
        if (controllerRef.current === controller) {
          controllerRef.current = null
        }
        busyRef.current = false
        setLoading(false)
      }
    },
    [appendError],
  )

  const selectCandidate = useCallback(
    async (sourceMessageId: string, candidate: TaskCandidate): Promise<boolean> => {
      if (busyRef.current) {
        return false
      }
      busyRef.current = true
      setLoading(true)
      setError(null)
      const tempUserId = nextMessageId('temp-user')
      setMessages((current) => [
        ...current,
        {
          id: tempUserId,
          role: 'user',
          content: `选择任务「${candidate.title}」`,
          action: null,
          candidates: [],
          promptVersion: null,
          createdAt: new Date().toISOString(),
        },
      ])
      try {
        const turn = await assistantApi.sendMessage(
          `选择任务「${candidate.title}」`,
          {
            selectedTaskId: candidate.id,
            sourceMessageId,
          },
        )
        setMessages((current) => [
          ...current
            .filter((message) => message.id !== tempUserId)
            .map((message) =>
              message.id === sourceMessageId
                ? { ...message, candidates: [] }
                : message,
            ),
          toChatMessage(turn.userMessage),
          toChatMessage(turn.assistantMessage),
        ])
        return true
      } catch (selectionError) {
        setMessages((current) =>
          current.filter((message) => message.id !== tempUserId),
        )
        appendError(getApiErrorMessage(selectionError))
        return false
      } finally {
        busyRef.current = false
        setLoading(false)
      }
    },
    [appendError],
  )

  const confirmAction = useCallback(
    async (
      actionId: string,
      confirm: boolean,
      payloadOverrides?: Record<string, unknown>,
    ) => {
      if (actionBusyId) {
        return null
      }
      setActionBusyId(actionId)
      setError(null)
      try {
        const result =
          payloadOverrides === undefined
            ? await assistantApi.confirm(actionId, confirm)
            : await assistantApi.confirm(actionId, confirm, payloadOverrides)
        setMessages((current) => [
          ...current.map((message) =>
            message.action?.id === actionId
              ? {
                  ...message,
                  action: message.action
                    ? { ...message.action, status: result.status }
                    : null,
                }
              : message,
          ),
          {
            id: nextMessageId(),
            role: 'assistant',
            content: result.message,
            action: null,
            candidates: [],
            promptVersion: null,
            createdAt: new Date().toISOString(),
          },
        ])
        if (confirm && result.status === 'confirmed') {
          await onTasksChanged()
        }
        return result
      } catch (confirmError) {
        if (confirmError instanceof ApiError && confirmError.code === 'ACTION_EXPIRED') {
          setMessages((current) =>
            current.map((message) =>
              message.action?.id === actionId && message.action
                ? {
                    ...message,
                    action: { ...message.action, status: 'expired' },
                  }
                : message,
            ),
          )
        }
        appendError(getApiErrorMessage(confirmError))
        return null
      } finally {
        setActionBusyId(null)
      }
    },
    [actionBusyId, appendError, onTasksChanged],
  )

  return {
    messages,
    loading,
    historyLoading,
    actionBusyId,
    error,
    sendMessage,
    selectCandidate,
    confirmAction,
    retryHistory,
  }
}
