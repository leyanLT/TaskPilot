import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Thin wrapper over the browser SpeechRecognition API (Chrome / Edge).
 * No audio ever leaves the page through TaskPilot itself: the browser's own
 * speech service performs recognition, and only the final transcript is used.
 */

interface SpeechResultEventLike {
  resultIndex: number
  results: ArrayLike<{ isFinal: boolean; 0: { transcript: string }; length: number }>
}

interface SpeechRecognitionLike {
  lang: string
  continuous: boolean
  interimResults: boolean
  start: () => void
  stop: () => void
  abort: () => void
  onresult: ((event: SpeechResultEventLike) => void) | null
  onerror: ((event: unknown) => void) | null
  onend: (() => void) | null
}

type SpeechRecognitionCtor = new () => SpeechRecognitionLike

function getCtor(): SpeechRecognitionCtor | null {
  if (typeof window === 'undefined') {
    return null
  }
  const scope = window as unknown as {
    SpeechRecognition?: SpeechRecognitionCtor
    webkitSpeechRecognition?: SpeechRecognitionCtor
  }
  return scope.SpeechRecognition ?? scope.webkitSpeechRecognition ?? null
}

export function useSpeechInput(onFinal: (text: string) => void) {
  const [supported] = useState(() => Boolean(getCtor()))
  const [listening, setListening] = useState(false)
  const [interim, setInterim] = useState('')
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null)
  const onFinalRef = useRef(onFinal)

  useEffect(() => {
    onFinalRef.current = onFinal
  }, [onFinal])

  useEffect(() => {
    return () => {
      recognitionRef.current?.abort?.()
    }
  }, [])

  const start = useCallback(() => {
    const Ctor = getCtor()
    if (!Ctor) {
      return
    }
    const recognition = new Ctor()
    recognition.lang = 'zh-CN'
    recognition.continuous = false
    recognition.interimResults = true
    recognition.onresult = (event) => {
      let finalText = ''
      let interimText = ''
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index]
        const text = result?.[0]?.transcript ?? ''
        if (result?.isFinal) {
          finalText += text
        } else {
          interimText += text
        }
      }
      setInterim(interimText)
      if (finalText.trim()) {
        setInterim('')
        onFinalRef.current(finalText.trim())
      }
    }
    recognition.onerror = () => {
      setListening(false)
      setInterim('')
    }
    recognition.onend = () => {
      setListening(false)
      setInterim('')
    }
    recognitionRef.current = recognition
    try {
      recognition.start()
      setListening(true)
    } catch {
      setListening(false)
    }
  }, [])

  const stop = useCallback(() => {
    recognitionRef.current?.stop()
    setListening(false)
    setInterim('')
  }, [])

  const toggle = useCallback(() => {
    if (listening) {
      stop()
    } else {
      start()
    }
  }, [listening, start, stop])

  return { supported, listening, interim, toggle, stop }
}
