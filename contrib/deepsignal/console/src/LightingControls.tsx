import { useEffect, useEffectEvent, useLayoutEffect, useState, useSyncExternalStore } from 'react'
import { createLighting } from './context'
import { isShortcut } from './lighting'
import type { LightingMode, NightPalette } from './lighting'

export function LightingControls({ defaultPalette, controller }: {
  defaultPalette?: NightPalette
  controller?: ReturnType<typeof createLighting>
}) {
  const [standalone] = useState(() => createLighting(defaultPalette))
  const lighting = controller ?? standalone
  const { mode, dayMode, dim, nightPalette } = useSyncExternalStore(lighting.subscribe, lighting.get)
  useLayoutEffect(() => lighting.paint(), [lighting])

  function selectMode(next: LightingMode) {
    lighting.set({ mode: next })
  }

  const onShortcut = useEffectEvent((event: KeyboardEvent) => {
    if (event.key.toLowerCase() === 'n' && isShortcut(event)) {
      selectMode(mode === 'night' ? dayMode : 'night')
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
        aria-keyshortcuts="N" onClick={() => selectMode(mode === 'night' ? dayMode : 'night')}>
        <svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
          <path d="M20 15.5A8.5 8.5 0 0 1 8.5 4a8.5 8.5 0 1 0 11.5 11.5z" />
        </svg>
        Night
      </button>
      {mode === 'night' && (
        <div className="night-settings">
          <label className="dim">
            Dim
            <input type="range" min="15" max="100" value={Math.round(dim * 100)}
              aria-label="Night brightness"
              aria-valuetext={`${Math.round(dim * 100)} percent`}
              onChange={(event) => lighting.set({ dim: Number(event.target.value) / 100 })}
            />
          </label>
          <div className="modes" role="group" aria-label="Night palette">
            <button type="button" aria-pressed={nightPalette === 'red'}
              onClick={() => lighting.set({ nightPalette: 'red' })}>Red</button>
            <button type="button" aria-pressed={nightPalette === 'neutral'}
              onClick={() => lighting.set({ nightPalette: 'neutral' })}>Neutral</button>
          </div>
        </div>
      )}
    </div>
  )
}
