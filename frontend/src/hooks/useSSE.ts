import { useEffect, useState, useRef, useCallback } from 'react'
import { sseUrl, type SSEEvent } from '@/lib/api'

export function useSSE(jobId: string | null) {
  const [events, setEvents] = useState<SSEEvent[]>([])
  const [isConnected, setIsConnected] = useState(false)
  const [isDone, setIsDone] = useState(false)
  const eventSourceRef = useRef<EventSource | null>(null)

  const disconnect = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
      eventSourceRef.current = null
      setIsConnected(false)
    }
  }, [])

  useEffect(() => {
    if (!jobId) {
      setEvents([])
      setIsDone(false)
      return
    }

    setEvents([])
    setIsDone(false)
    const es = new EventSource(sseUrl(jobId))
    eventSourceRef.current = es

    es.onopen = () => setIsConnected(true)

    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data) as SSEEvent & { status: string }
        if (data.status === 'done' || data.status === 'timeout' || data.status === 'completed' || data.status === 'failed') {
          setIsDone(true)
          es.close()
          setIsConnected(false)
          return
        }
        setEvents((prev) => [...prev, data])
      } catch {
        // ignore parse errors
      }
    }

    es.onerror = () => {
      setIsConnected(false)
      es.close()
    }

    return () => {
      es.close()
      setIsConnected(false)
    }
  }, [jobId])

  const latestEvent = events.length > 0 ? events[events.length - 1] : null

  return { events, latestEvent, isConnected, isDone, disconnect }
}
