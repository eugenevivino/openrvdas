import { expect, it } from 'vitest'
import { mergeFieldSamples } from './field-data'
import type { FieldSamples } from './field-data'

it('keeps cadence bounded and stable through repeated disconnected observation periods', () => {
  let samples: FieldSamples | undefined
  let time = 1_000
  const reading = () => ({ timestamp: time, receivedAt: time, value: 'OK' })
  samples = mergeFieldSamples(samples, [reading()], [])
  for (let epoch = 0; epoch < 100; epoch++) {
    samples = mergeFieldSamples(samples, [reading()], [], { resumed: true })
    for (let i = 0; i < 2; i++) {
      time++
      samples = mergeFieldSamples(samples, [reading()], [])
    }
    expect(samples.learnedPeriod).toBe(1)
    expect(samples.cadence!.length).toBeLessThanOrEqual(41)
  }
})
