export interface Reading {
  value: unknown
  timestamp: number
  receivedAt: number
}

export type Freshness = 'LIVE' | 'AGING' | 'STALE' | 'NO DATA'
export type Quality = 'PASS' | 'NOT EVALUATED' | 'SUSPECT' | 'FAIL' | 'MISSING'

interface OlderReading {
  reading: Reading
  nextTimestamp: number
}

export interface FieldSamples {
  recent: readonly Reading[]
  flags: readonly Reading[]
  olderGood: readonly OlderReading[]
  lastGood?: Reading
  quality: Quality
  learnedPeriod?: number
}

const intervalCount = 20
const olderGoodLimit = 2
const provisionalPeriod = 1

export function qualityFromFlag(flag: unknown): Quality {
  switch (flag) {
    case 1: return 'PASS'
    case 3: return 'SUSPECT'
    case 4: return 'FAIL'
    case 9: return 'MISSING'
    default: return 'NOT EVALUATED'
  }
}

function isGood(quality: Quality) {
  return quality === 'PASS' || quality === 'NOT EVALUATED'
}

export function mergeReadings(previous: readonly Reading[], incoming: readonly Reading[]) {
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
  const previousOlder = previous?.olderGood ?? []
  const samples = mergeReadings([...previousOlder.map(({ reading }) => reading), ...(previous?.recent ?? [])], readings)
  const qualitySamples = mergeReadings(previous?.flags ?? [], flags)
  const recent = samples.slice(-intervalCount - 1)
  const firstRecent = samples.length - recent.length
  const usedFlags = new Set(qualitySamples.slice(-intervalCount - 1))
  const olderBoundaries = previousOlder.map(({ nextTimestamp }) => nextTimestamp).sort((a, b) => a - b)
  const olderGood: Array<OlderReading & { flag?: Reading }> = []
  let flagIndex = 0
  let lastGood: Reading | undefined
  let quality = qualityFromFlag(qualitySamples.at(-1)?.value)

  for (const [index, sample] of samples.entries()) {
    // A flag applies to the reading at that timestamp, or to the preceding
    // reading when a flag arrives separately. A newer reading needs its own flag.
    // A known next timestamp still splits QC intervals after that reading is evicted.
    const nextTimestamp = Math.min(samples[index + 1]?.timestamp ?? Infinity,
      olderBoundaries.find((boundary) => boundary > sample.timestamp) ?? Infinity)
    let matched: Reading | undefined
    while (flagIndex < qualitySamples.length && qualitySamples[flagIndex].timestamp < nextTimestamp) {
      matched = qualitySamples[flagIndex++]
    }
    if (matched && matched.timestamp < sample.timestamp) matched = undefined
    if (matched) {
      quality = qualityFromFlag(matched.value)
      if (index >= firstRecent) usedFlags.add(matched)
    } else {
      quality = 'NOT EVALUATED'
    }
    if (sample.value != null && isGood(quality)) {
      lastGood = sample
      if (index < firstRecent) {
        // Retain a fallback if delayed QC revokes the newest evicted good reading.
        olderGood.push({ reading: sample, nextTimestamp, flag: matched })
        if (olderGood.length > olderGoodLimit) olderGood.shift()
      }
    }
  }
  for (const { flag } of olderGood) if (flag) usedFlags.add(flag)

  const intervals = recent.slice(1).map(({ timestamp }, index) => timestamp - recent[index].timestamp)
    .sort((a, b) => a - b)
  const middle = Math.floor(intervals.length / 2)
  const learnedPeriod = !intervals.length ? undefined
    : intervals.length % 2 ? intervals[middle] : (intervals[middle - 1] + intervals[middle]) / 2
  return { recent, flags: [...usedFlags], olderGood: olderGood.map(({ reading, nextTimestamp }) => ({ reading, nextTimestamp })),
    lastGood, quality, learnedPeriod }
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
