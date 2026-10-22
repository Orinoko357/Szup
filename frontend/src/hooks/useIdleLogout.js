import { useEffect, useRef } from 'react'
import { clearSession } from '../roles'

const IDLE_TIMEOUT_MS = 30 * 60 * 1000 // 30 minut

export default function useIdleLogout(isLoggedIn) {
  const timerRef = useRef(null)

  useEffect(() => {
    if (!isLoggedIn) return

    const reset = () => {
      clearTimeout(timerRef.current)
      timerRef.current = setTimeout(() => {
        clearSession()
        window.location.href = '/login?reason=idle'
      }, IDLE_TIMEOUT_MS)
    }

    const events = ['mousemove', 'keydown', 'click', 'scroll', 'touchstart']
    events.forEach(e => window.addEventListener(e, reset, { passive: true }))
    reset()

    return () => {
      events.forEach(e => window.removeEventListener(e, reset))
      clearTimeout(timerRef.current)
    }
  }, [isLoggedIn])
}
