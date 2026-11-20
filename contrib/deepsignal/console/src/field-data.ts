export interface Reading {
  value: unknown
  timestamp: number
  receivedAt: number
}

export type Freshness = 'LIVE' | 'AGING' | 'STALE' | 'NO DATA'
export type Quality = 'PASS' | 'NOT EVALUATED' | 'SUSPECT' | 'FAIL' | 'MISSING'

interface Flag extends Reading {
  epoch: number
}

interface ObservationGap {
  after: number
  before: number
  epoch: number
}

interface FlagRange {
  first: number
  last: number
}

export interface FieldEvidence {
  points: readonly Reading[]
  flags: readonly Flag[]
  gaps: readonly ObservationGap[]
  discardedRejections: readonly FlagRange[]
  epoch: number
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

export function mergeReadings<T extends Reading>(previous: readonly T[], incoming: readonly T[]) {
  const byTimestamp = new Map(previous.map((reading) => [reading.timestamp, reading]))
  for (const reading of incoming) {
    if (byTimestamp.get(reading.timestamp)?.value !== reading.value) {
      byTimestamp.set(reading.timestamp, reading)
    }
  }
  return [...byTimestamp.values()].sort((a, b) => a.timestamp - b.timestamp)
}

function observationGaps(previous: readonly ObservationGap[], reopened: ObservationGap | undefined,
  points: readonly Reading[], incoming: readonly Reading[]) {
  if (!previous.length && !reopened) return previous
  const from = incoming.reduce((first, { timestamp }) => Math.min(first, timestamp), Infinity)
  const through = incoming.reduce((last, { timestamp }) => Math.max(last, timestamp), -Infinity)
  const oldest = points[0]?.timestamp ?? Infinity
  const gaps: ObservationGap[] = []
  for (const gap of reopened ? [...previous, reopened] : previous) {
    if (gap.before <= oldest) continue
    if (gap.before === Infinity) {
      if (through < gap.after) gaps.push(gap)
      else if (from > gap.after) gaps.push({ ...gap, before: from })
    } else if (from >= gap.before || through <= gap.after || from === through) {
      gaps.push(gap)
    } else {
      // A contiguous batch can prove part or all of an earlier gap.
      if (gap.after < from) gaps.push({ ...gap, before: from })
      if (through < gap.before) gaps.push({ ...gap, after: through })
    }
  }
  return gaps
}

function retainDiscardedRejections(previous: readonly FlagRange[], incoming: readonly FlagRange[], oldest: number) {
  if (!incoming.length) {
    return previous.length && previous[0].last < oldest ? previous.filter(({ last }) => last >= oldest) : previous
  }
  const ranges: FlagRange[] = []
  for (const range of [...previous, ...incoming].sort((a, b) => a.first - b.first)) {
    if (range.last < oldest) continue
    const tail = ranges.at(-1)
    if (tail && range.first <= tail.last) {
      ranges[ranges.length - 1] = { first: tail.first, last: Math.max(tail.last, range.last) }
    } else {
      ranges.push(range)
    }
  }
  if (ranges.length <= maxHistoryPoints) return ranges
  // At the cap, coalesce the oldest spans conservatively.
  const split = ranges.length - maxHistoryPoints
  return [{ first: ranges[0].first, last: ranges[split].last }, ...ranges.slice(split + 1)]
}

export function mergeFieldSamples(previous: FieldSamples | undefined, readings: readonly Reading[],
  flags: readonly Reading[], { evidence = previous?.evidence, latestOnly = false, resumed = false } = {}): FieldSamples {
  const retained = evidence?.points ?? []
  const points = readings.length ? mergeReadings(retained, readings).slice(-maxHistoryPoints) : retained
  const epoch = (evidence?.epoch ?? 0) + Number(resumed)
  const lastObserved = retained.at(-1)?.timestamp
  const priorGaps = evidence?.gaps ?? []
  const reopened = resumed && lastObserved !== undefined && priorGaps.at(-1)?.before !== Infinity
    ? { after: lastObserved, before: Infinity, epoch } : undefined
  const gaps = observationGaps(priorGaps, reopened, points, readings)
  const qualitySamples = flags.length
    ? mergeReadings(evidence?.flags ?? [], flags.map((flag) => ({ ...flag, epoch }))) : evidence?.flags ?? []
  // Retain the raw tail and the decisive flags of older intervals. Reserve extra
  // space for QC on non-null readings so later backfill can split their intervals.
  const rawTail = qualitySamples.length > maxHistoryPoints
    ? new Set(qualitySamples.slice(-maxHistoryPoints)) : undefined
  let archiveRemaining = maxHistoryPoints
  const discarded = evidence?.discardedRejections ?? []
  const newlyDiscarded: FlagRange[] = []

  // Only measurements delivered to the active subscription can set freshness.
  const previousRecent = previous?.recent ?? []
  const earliest = latestOnly && !previousRecent.length ? lastObserved ?? -Infinity : -Infinity
  const current = earliest === -Infinity ? readings : readings.filter(({ timestamp }) => timestamp >= earliest)
  const recent = current.length ? mergeReadings(previousRecent, current).slice(-intervalCount - 1) : previousRecent
  const latest = recent.at(-1)
  let flagIndex = 0
  let gapIndex = 0
  let discardedIndex = 0
  let lastGood: Reading | undefined
  let quality = qualityFromFlag(latest ? undefined : qualitySamples.at(-1)?.value)

  for (let index = 0; index < points.length; index++) {
    const sample = points[index]
    const nextTimestamp = points[index + 1]?.timestamp ?? Infinity
    let matched: Flag | undefined
    let firstRejected: Flag | undefined
    let lostFirst: number | undefined
    let lostLast: number | undefined
    while (flagIndex < qualitySamples.length && qualitySamples[flagIndex].timestamp < nextTimestamp) {
      const flag = qualitySamples[flagIndex++]
      if (flag.timestamp < sample.timestamp) continue
      while (gapIndex < gaps.length && gaps[gapIndex].before <= flag.timestamp) gapIndex++
      const gap = gaps[gapIndex]
      // A new flag inside an observation gap has no defensible preceding
      // reading. Exact timestamps and QC seen before the gap retain provenance.
      if (flag.timestamp !== sample.timestamp && gap && gap.after < flag.timestamp && flag.epoch >= gap.epoch) continue
      if (rawTail) {
        if (!firstRejected && !isGood(qualityFromFlag(flag.value))) {
          firstRejected = flag
          rawTail.add(flag)
        }
        if (archiveRemaining > 0 && sample.value != null && !rawTail.has(flag)) {
          rawTail.add(flag)
          archiveRemaining--
        }
        if (matched && !rawTail.has(matched) && !isGood(qualityFromFlag(matched.value))) {
          lostFirst ??= matched.timestamp
          lostLast = matched.timestamp
        }
      }
      matched = flag
    }
    if (matched) rawTail?.add(matched)
    if (lostFirst !== undefined) newlyDiscarded.push({ first: lostFirst, last: lostLast! })

    const sampleQuality = qualityFromFlag(matched?.value)
    if (sample.timestamp === latest?.timestamp) quality = sampleQuality
    if (sample.value == null || !isGood(sampleQuality)) continue
    // A prior rejection must not become an eligible Last value just because
    // its precise QC record exceeded the bounded archive before backfill.
    while (discardedIndex < discarded.length && (discarded[discardedIndex].last < sample.timestamp ||
      discarded[discardedIndex].last <= (matched?.timestamp ?? -Infinity))) discardedIndex++
    const possibleRejection = discarded[discardedIndex]
    if (!possibleRejection || possibleRejection.first >= nextTimestamp) lastGood = sample
  }

  const intervals = recent.slice(1).map(({ timestamp }, index) => timestamp - recent[index].timestamp)
    .sort((a, b) => a - b)
  const middle = Math.floor(intervals.length / 2)
  const learnedPeriod = !intervals.length ? undefined
    : intervals.length % 2 ? intervals[middle] : (intervals[middle - 1] + intervals[middle]) / 2
  return {
    recent, lastGood, quality, learnedPeriod,
    evidence: {
      points, gaps, epoch,
      flags: rawTail ? qualitySamples.filter((flag) => rawTail.has(flag)) : qualitySamples,
      discardedRejections: retainDiscardedRejections(discarded, newlyDiscarded, points[0]?.timestamp ?? Infinity),
    },
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
