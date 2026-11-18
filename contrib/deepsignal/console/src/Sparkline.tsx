import { useEffect, useRef } from 'react'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'
import type { Reading } from './cds'

function plotData(history: readonly Reading[], staleAfter: number): uPlot.AlignedData {
  const timestamps: number[] = []
  const values: (number | null)[] = []
  for (const { timestamp, value } of history) {
    const previous = timestamps.at(-1)
    if (previous !== undefined && timestamp - previous > staleAfter) {
      timestamps.push((previous + timestamp) / 2)
      values.push(null)
    }
    timestamps.push(timestamp)
    values.push(value)
  }
  return [timestamps, values]
}

export function Sparkline({ history, now, minutes, staleAfter }: {
  history: readonly Reading[]
  now: number
  minutes: number
  staleAfter: number
}) {
  const container = useRef<HTMLDivElement>(null)
  const chart = useRef<uPlot | null>(null)

  useEffect(() => {
    const element = container.current!
    const color = () => getComputedStyle(document.documentElement).getPropertyValue('--chart').trim()
    const plot = new uPlot({
      width: Math.max(1, element.clientWidth),
      height: 46,
      legend: { show: false },
      cursor: { show: false },
      axes: [],
      padding: [3, 1, 3, 1],
      series: [{}, { stroke: color, width: 1.8, spanGaps: false, points: { show: false } }],
    }, [[], []], element)
    chart.current = plot
    const resize = new ResizeObserver(([entry]) => {
      plot.setSize({ width: Math.max(1, Math.floor(entry.contentRect.width)), height: 46 })
    })
    resize.observe(element)
    const repaint = () => plot.redraw()
    window.addEventListener('consolelighting', repaint)
    return () => {
      window.removeEventListener('consolelighting', repaint)
      resize.disconnect()
      plot.destroy()
      chart.current = null
    }
  }, [])

  useEffect(() => {
    chart.current?.setData(plotData(history, staleAfter), false)
  }, [history, staleAfter])

  useEffect(() => {
    chart.current?.setScale('x', { min: now - minutes * 60, max: now + 1 })
  }, [history, minutes, now, staleAfter])

  return <div className="sparkline" ref={container} aria-hidden="true" />
}
