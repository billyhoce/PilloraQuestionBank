import { useEffect, useLayoutEffect, useRef } from 'react'

// Call `fn` every `ms` while `enabled`, skipping ticks while the tab is hidden and catching up as
// soon as it is shown again. Stops on unmount. `fn` may change between renders; the latest is used.
export default function usePoll(fn, ms, enabled = true) {
  const latest = useRef(fn)
  useLayoutEffect(() => { latest.current = fn })

  useEffect(() => {
    if (!enabled) return undefined
    const hidden = () => typeof document !== 'undefined' && document.visibilityState === 'hidden'
    const id = setInterval(() => { if (!hidden()) latest.current() }, ms)
    const onShow = () => { if (!hidden()) latest.current() }
    document.addEventListener('visibilitychange', onShow)
    return () => {
      clearInterval(id)
      document.removeEventListener('visibilitychange', onShow)
    }
  }, [ms, enabled])
}
