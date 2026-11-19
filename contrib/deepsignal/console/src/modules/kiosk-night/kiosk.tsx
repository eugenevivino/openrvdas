import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import type { ConsoleContext } from '../../contract'
import { autoNightStatus, subscribeAutoNightStatus } from './autoNight'
import { parseKioskHash } from './hash'

function configuredPage(ctx: ConsoleContext): string | undefined {
  const page = ctx.config.modules['kiosk-night']?.kiosk_page
  return typeof page === 'string' && page ? page : undefined
}

export function KioskSlot({ ctx }: { ctx: ConsoleContext }) {
  const [page] = useState(() => parseKioskHash(window.location.hash) ?? configuredPage(ctx))
  const [active, setActive] = useState(() => Boolean(page))
  const [wakeFailed, setWakeFailed] = useState(false)
  const autoStatus = useSyncExternalStore(
    (listener) => subscribeAutoNightStatus(ctx, listener),
    () => autoNightStatus(ctx),
  )
  const pressStart = useRef<number | undefined>(undefined)
  const wakeLock = useRef<WakeLockSentinel | undefined>(undefined)
  const wakeEffectActive = useRef(false)

  useEffect(() => {
    if (!active || !page) return
    if (ctx.route.get() !== page) ctx.route.go(page)
    const blockNumbers = (event: KeyboardEvent) => {
      if (/^[1-9]$/.test(event.key)) {
        event.preventDefault()
        event.stopImmediatePropagation()
      }
    }
    window.addEventListener('keydown', blockNumbers, true)
    return () => window.removeEventListener('keydown', blockNumbers, true)
  }, [active, ctx, page])

  useEffect(() => {
    if (!active) return
    wakeEffectActive.current = true
    const request = async () => {
      try {
        if (!('wakeLock' in navigator)) {
          setWakeFailed(true)
          return
        }
        wakeLock.current = await navigator.wakeLock.request('screen')
        if (!wakeLock.current) setWakeFailed(true)
        else if (wakeEffectActive.current) setWakeFailed(false)
      } catch {
        if (wakeEffectActive.current) setWakeFailed(true)
      }
    }
    const visible = () => { if (document.visibilityState === 'visible') void request() }
    void request()
    document.addEventListener('visibilitychange', visible)
    return () => {
      wakeEffectActive.current = false
      document.removeEventListener('visibilitychange', visible)
      void wakeLock.current?.release()
      wakeLock.current = undefined
    }
  }, [active])

  if (!active || !page) {
    return autoStatus ? <span role="status">□ {autoStatus}</span> : null
  }
  const exit = () => {
    if (pressStart.current !== undefined && ctx.clock.now() - pressStart.current >= 2) {
      setActive(false)
      ctx.route.go(page)
    }
    pressStart.current = undefined
  }
  return (
    <>
      <style>{'.tabs{display:none!important}.bar .live,.bar .clock,.lighting .modes{display:none!important}'}</style>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--muted)', fontFamily: 'var(--f-body)', fontSize: '16px' }}>
        <button type="button" aria-label="Exit kiosk (hold for two seconds)"
          onPointerDown={() => { pressStart.current = ctx.clock.now() }} onPointerUp={exit}
          onPointerCancel={() => { pressStart.current = undefined }}
          style={{ minWidth: '44px', minHeight: '44px', color: 'var(--fg)', background: 'var(--panel)', border: '1px solid var(--line)', borderRadius: '6px' }}>
          Kiosk
        </button>
        {wakeFailed && <span role="status">Screen may sleep</span>}
        {autoStatus && <span role="status">□ {autoStatus}</span>}
      </div>
    </>
  )
}
