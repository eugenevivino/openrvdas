type Shape = 'circle' | 'triangle' | 'square' | 'cross' | 'diamond' | 'dash'

export function Status({ shape, tone, children }: {
  shape: Shape
  tone: string
  children: string
}) {
  return (
    <span className={'status status-' + tone}>
      <svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
        {shape === 'circle' && <circle cx="6" cy="6" r="5" fill="currentColor" />}
        {shape === 'triangle' && <path d="M6 1 11 11H1Z" fill="currentColor" />}
        {shape === 'square' && <rect x="1.5" y="1.5" width="9" height="9" fill="none" stroke="currentColor" strokeWidth="2" />}
        {shape === 'cross' && <path d="M2 2l8 8m0-8-8 8" stroke="currentColor" strokeWidth="2.4" />}
        {shape === 'diamond' && <path d="m6 1 5 5-5 5-5-5Z" fill="none" stroke="currentColor" strokeWidth="1.5" />}
        {shape === 'dash' && <path d="M1 6h10" stroke="currentColor" strokeWidth="2" />}
      </svg>
      {children}
    </span>
  )
}
