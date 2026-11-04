import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AssistantStreamEvent } from '../../types'
import { assistantApi } from '../assistant'
import { ApiError } from '../http'

const userMessage = {
  id: 'user-1',
  role: 'user',
  content: '你好',
  action: null,
  candidates: [],
  prompt_version: null,
  created_at: '2026-01-01T08:00:00+00:00',
}

const assistantMessage = {
  id: 'assistant-1',
  role: 'assistant',
  content: '你好，我在。',
  action: null,
  candidates: [],
  prompt_version: '2026-11-v4',
  created_at: '2026-01-01T08:00:01+00:00',
}

function streamResponse(blocks: string[]): Response {
  const encoder = new TextEncoder()
  const chunks = blocks.map((block) => encoder.encode(block))
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(chunk)
      }
      controller.close()
    },
  })
  return new Response(stream, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  })
}

describe('assistantApi.streamMessage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('parses split SSE events and maps them to typed events', async () => {
    const started = `event: started\ndata: ${JSON.stringify({
      user_message: userMessage,
      prompt_version: '2026-11-v4',
    })}\n\n`
    const fetchMock = vi.fn().mockResolvedValue(
      streamResponse([
        started.slice(0, 28),
        started.slice(28),
        `event: token\ndata: {"delta":"你"}\n\nevent: token\ndata: {"delta":"好"}\n\n`,
        `event: done\ndata: ${JSON.stringify({
          assistant_message: assistantMessage,
        })}\n\n`,
      ]),
    )
    vi.stubGlobal('fetch', fetchMock)

    const events: AssistantStreamEvent[] = []
    for await (const event of assistantApi.streamMessage('你好')) {
      events.push(event)
    }

    expect(events.map((event) => event.type)).toEqual([
      'started',
      'token',
      'token',
      'done',
    ])
    expect(events[0]).toMatchObject({
      type: 'started',
      promptVersion: '2026-11-v4',
      userMessage: { id: 'user-1', role: 'user' },
    })
    expect(events[2]).toEqual({ type: 'token', delta: '好' })
    expect(events[3]).toMatchObject({
      type: 'done',
      assistantMessage: { id: 'assistant-1', content: '你好，我在。' },
    })
  })

  it('throws a typed error for a non-streaming error response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: { code: 'AI_NOT_CONFIGURED', message: 'AI 尚未配置。' },
          }),
          {
            status: 503,
            headers: { 'Content-Type': 'application/json' },
          },
        ),
      ),
    )

    const error = await assistantApi
      .streamMessage('你好')
      .next()
      .catch((caught: unknown) => caught)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({
      code: 'AI_NOT_CONFIGURED',
      status: 503,
    })
  })
})
