import { useEffect, useRef } from 'react'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'
import type { ConsoleContext } from '../../contract'

type Sample = ReturnType<ConsoleContext['store']['history']>[number]

function plotData(history: readonly Sample[], period: number): uPlot.AlignedData {
  const timestamps: number[] = []
  const values: (number | null)[] = []
  for (const { time: timestamp, value } of history) {
    const previous = timestamps.at(-1)
    if (previous !== undefined && timestamp - previous > 5 * period) {
      timestamps.push((previous + timestamp) / 2)
      values.push(null)
    }
    timestamps.push(timestamp)
    values.push(typeof value === 'number' ? value : null)
  }
  return [timestamps, values]
}

export function Sparkline({ history, now, minutes, period, lighting }: {
  history: readonly Sample[]
  now: number
  minutes: number
  period: number
  lighting: ConsoleContext['lighting']
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
    const unsubscribe = lighting.subscribe(() => plot.redraw())
    return () => {
      unsubscribe()
      resize.disconnect()
      plot.destroy()
      chart.current = null
    }
  }, [lighting])

  useEffect(() => {
    chart.current?.setData(plotData(history, period), false)
  }, [history, period])

  useEffect(() => {
    chart.current?.setScale('x', { min: now - minutes * 60, max: now + 1 })
  }, [history, minutes, now, period])

  return <div className="sparkline" ref={container} aria-hidden="true" />
}
