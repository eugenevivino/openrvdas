export interface Reading {
  value: number | null
  timestamp: number
  receivedAt: number
}

export type Freshness = 'LIVE' | 'AGING' | 'STALE' | 'NO DATA'
export type Quality = 'PASS' | 'NOT EVALUATED' | 'SUSPECT' | 'FAIL' | 'MISSING'

export interface FieldSamples {
  recent: readonly Reading[]
  flags: readonly Reading[]
  olderGood?: Reading
  lastGood?: Reading
  quality: Quality
  learnedPeriod?: number
}

const intervalCount = 20
const provisionalPeriod = 1

export function qualityFromFlag(flag: number | null | undefined): Quality {
  switch (flag) {
    case 1: return 'PASS'
    case 3: return 'SUSPECT'
    case 4: return 'FAIL'
    case 9: return 'MISSING'
    default: return 'NOT EVALUATED'
  }
}

function mergeReadings(previous: readonly Reading[], incoming: readonly Reading[]) {
  const byTimestamp = new Map(previous.map((reading) => [reading.timestamp, reading]))
  for (const reading of incoming) {
    if (byTimestamp.get(reading.timestamp)?.value !== reading.value) {
      byTimestamp.set(reading.timestamp, reading)
    }
  }
  return [...byTimestamp.values()].sort((a, b) => a.timestamp - b.timestamp)
}

export function mergeFieldSamples(previous: FieldSamples | undefined, readings: readonly Reading[],
  flags: readonly Reading[]): FieldSamples {
  const samples = mergeReadings(previous?.recent ?? [], readings)
  const qualitySamples = mergeReadings(previous?.flags ?? [], flags)
  const recent = samples.slice(-intervalCount - 1)
  const firstRecent = samples.length - recent.length
  const usedFlags = new Set(qualitySamples.slice(-intervalCount - 1))
  let flagIndex = 0
  // Once a good reading leaves the recent window, keep it independently so
  // flags from other expired readings cannot be attributed to it.
  let olderGood = previous?.olderGood
  let lastGood = olderGood
  let quality = qualityFromFlag(qualitySamples.at(-1)?.value)

  for (const [index, sample] of samples.entries()) {
    // A flag applies to the reading at that timestamp, or to the preceding
    // reading when a flag arrives separately. A newer reading needs its own flag.
    const nextTimestamp = samples[index + 1]?.timestamp ?? Infinity
    let matched: Reading | undefined
    while (flagIndex < qualitySamples.length && qualitySamples[flagIndex].timestamp < nextTimestamp) {
      matched = qualitySamples[flagIndex++]
    }
    if (matched && matched.timestamp >= sample.timestamp) {
      quality = qualityFromFlag(matched.value)
      if (index >= firstRecent) usedFlags.add(matched)
    } else {
      quality = 'NOT EVALUATED'
    }
    if (sample.value !== null && (quality === 'PASS' || quality === 'NOT EVALUATED') &&
        (lastGood === undefined || sample.timestamp > lastGood.timestamp)) {
      lastGood = sample
      if (index < firstRecent) olderGood = sample
    }
  }

  const intervals = recent.slice(1).map(({ timestamp }, index) => timestamp - recent[index].timestamp)
    .sort((a, b) => a - b)
  const middle = Math.floor(intervals.length / 2)
  const learnedPeriod = !intervals.length ? undefined
    : intervals.length % 2 ? intervals[middle] : (intervals[middle - 1] + intervals[middle]) / 2
  return { recent, flags: [...usedFlags], olderGood, lastGood, quality, learnedPeriod }
}

export function fieldData(samples: FieldSamples | undefined, period: number | undefined, now: number) {
  const latest = samples?.recent.at(-1)
  const expectedPeriod = period ?? samples?.learnedPeriod ?? provisionalPeriod
  const age = latest ? Math.max(0, now - latest.timestamp) : undefined
  let freshness: Freshness = 'NO DATA'
  if (age !== undefined) {
    if (age <= 2 * expectedPeriod) freshness = 'LIVE'
    else if (age <= 5 * expectedPeriod) freshness = 'AGING'
    else if (age <= Math.max(300, 60 * expectedPeriod)) freshness = 'STALE'
  }
  return {
    value: latest?.value ?? null,
    timestamp: latest?.timestamp,
    receivedAt: latest?.receivedAt,
    expectedPeriod,
    freshness,
    quality: samples?.quality ?? ('NOT EVALUATED' as const),
    health: 'UNKNOWN' as const,
    ai: 'NONE' as const,
    age,
    lastGood: samples?.lastGood,
  }
}
