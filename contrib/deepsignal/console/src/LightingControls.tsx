import { useEffect, useEffectEvent, useLayoutEffect, useState } from 'react'
import { isShortcut, paintLighting, readLighting, storeLighting } from './lighting'
import type { LightingMode } from './lighting'

export function LightingControls() {
  const [lighting, setLighting] = useState(readLighting)
  const { mode, lastDay, dim } = lighting

  useLayoutEffect(() => {
    paintLighting(document.documentElement, mode, dim)
    storeLighting(lighting)
    window.dispatchEvent(new Event('consolelighting'))
  }, [lighting, mode, dim])

  function selectMode(next: LightingMode) {
    setLighting({ mode: next, lastDay: next === 'night' ? lastDay : next, dim })
  }

  const onShortcut = useEffectEvent((event: KeyboardEvent) => {
    if (event.key.toLowerCase() === 'n' && isShortcut(event)) {
      selectMode(mode === 'night' ? lastDay : 'night')
    }
  })

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => onShortcut(event)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <div className="lighting">
      <div className="modes" role="group" aria-label="Lighting">
        <button type="button" aria-pressed={mode === 'day'} onClick={() => selectMode('day')}>Day</button>
        <button type="button" aria-pressed={mode === 'dusk'} onClick={() => selectMode('dusk')}>Dusk</button>
      </div>
      <button type="button" className="night-button" aria-pressed={mode === 'night'}
        aria-keyshortcuts="N" onClick={() => selectMode(mode === 'night' ? lastDay : 'night')}>
        <svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
          <path d="M20 15.5A8.5 8.5 0 0 1 8.5 4a8.5 8.5 0 1 0 11.5 11.5z" />
        </svg>
        Night
      </button>
      {mode === 'night' && (
        <label className="dim">
          Dim
          <input type="range" min="15" max="100" value={Math.round(dim * 100)}
            aria-label="Night brightness"
            aria-valuetext={`${Math.round(dim * 100)} percent`}
            onChange={(event) => setLighting({ ...lighting, dim: Number(event.target.value) / 100 })}
          />
        </label>
      )}
    </div>
  )
}
