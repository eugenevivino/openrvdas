export interface Reading {
  value: unknown
  timestamp: number
  receivedAt: number
}

export type Freshness = 'LIVE' | 'AGING' | 'STALE' | 'NO DATA'
export type Quality = 'PASS' | 'NOT EVALUATED' | 'SUSPECT' | 'FAIL' | 'MISSING'

export interface FieldEvidence {
  points: readonly Reading[]
  flags: readonly Reading[]
}

export interface FieldSamples {
  recent: readonly Reading[]
  evidence: FieldEvidence
  lastGood?: Reading
  quality: Quality
  learnedPeriod?: number
}

const intervalCount = 20
export const maxHistoryPoints = 10_000
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
  flags: readonly Reading[], { evidence = previous?.evidence, latestOnly = false } = {}): FieldSamples {
  const retained = evidence?.points ?? []
  const points = readings.length ? mergeReadings(retained, readings).slice(-maxHistoryPoints) : retained
  const qualitySamples = flags.length ? mergeReadings(evidence?.flags ?? [], flags) : evidence?.flags ?? []
  // Keep the raw QC tail for flags arriving ahead of their readings. Also keep
  // the latest flag in every retained reading's interval, even past that tail.
  const usedFlags = qualitySamples.length > maxHistoryPoints
    ? new Set(qualitySamples.slice(-maxHistoryPoints)) : undefined

  // Only measurements delivered to the active subscription can set freshness.
  const previousRecent = previous?.recent ?? []
  const earliest = latestOnly && !previousRecent.length ? retained.at(-1)?.timestamp ?? -Infinity : -Infinity
  const current = earliest === -Infinity ? readings : readings.filter(({ timestamp }) => timestamp >= earliest)
  const recent = current.length ? mergeReadings(previousRecent, current).slice(-intervalCount - 1) : previousRecent
  const latest = recent.at(-1)
  let flagIndex = 0
  let lastGood: Reading | undefined
  let quality = qualityFromFlag(latest ? undefined : qualitySamples.at(-1)?.value)

  for (let index = 0; index < points.length; index++) {
    const sample = points[index]
    // A flag applies to the reading at that timestamp, or to the preceding
    // reading when a flag arrives separately. A newer reading needs its own flag.
    const nextTimestamp = points[index + 1]?.timestamp ?? Infinity
    let matched: Reading | undefined
    while (flagIndex < qualitySamples.length && qualitySamples[flagIndex].timestamp < nextTimestamp) {
      matched = qualitySamples[flagIndex++]
    }
    if (matched && matched.timestamp < sample.timestamp) matched = undefined
    if (matched) usedFlags?.add(matched)
    const sampleQuality = qualityFromFlag(matched?.value)
    if (sample.timestamp === latest?.timestamp) quality = sampleQuality
    if (sample.value != null && isGood(sampleQuality)) lastGood = sample
  }

  const intervals = recent.slice(1).map(({ timestamp }, index) => timestamp - recent[index].timestamp)
    .sort((a, b) => a - b)
  const middle = Math.floor(intervals.length / 2)
  const learnedPeriod = !intervals.length ? undefined
    : intervals.length % 2 ? intervals[middle] : (intervals[middle - 1] + intervals[middle]) / 2
  return {
    recent, lastGood, quality, learnedPeriod,
    evidence: { points, flags: usedFlags ? qualitySamples.filter((flag) => usedFlags.has(flag)) : qualitySamples },
  }
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
