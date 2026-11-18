import type { FieldDescription } from '../../contract'

export type Role =
  | 'heading' | 'course' | 'speedOverGround' | 'latitude' | 'longitude'
  | 'trueWindSpeed' | 'trueWindDirection' | 'averagedWind'
  | 'airTemperature' | 'humidity' | 'barometer'
  | 'seaTemperature' | 'salinity' | 'fluorescence' | 'depth'
  | 'numeric'

export interface RecognitionRule {
  role: Role
  name: RegExp
  units?: RegExp
  description?: RegExp
}

/** Ordered from specific to generic; the first matching field wins for each named role. */
export const rules: RecognitionRule[] = [
  { role: 'heading', name: /(?:headingtrue|heading|hdg)/i, units: /(?:deg|degree)/i, description: /heading/i },
  { role: 'course', name: /(?:coursetrue|course|cog)/i, units: /(?:deg|degree)/i, description: /course over ground/i },
  { role: 'speedOverGround', name: /(?:speedkt|speedoverground|sog)/i, units: /(?:kt|knot|m\/?s)/i, description: /speed over ground/i },
  { role: 'latitude', name: /(?:latitude|\blat\b)/i, units: /(?:deg|degree)/i, description: /latitude/i },
  { role: 'longitude', name: /(?:longitude|\blon(?:g)?\b)/i, units: /(?:deg|degree)/i, description: /longitude/i },
  { role: 'averagedWind', name: /avg.*wind|wind.*avg/i, description: /(?:mean|average).*wind|wind.*(?:mean|average)/i },
  { role: 'trueWindSpeed', name: /truewindspeed|tws/i, units: /(?:kt|knot|m\/?s)/i, description: /true wind speed/i },
  { role: 'trueWindDirection', name: /truewind(?:dir|direction)|twd/i, units: /(?:deg|degree)/i, description: /true wind direction/i },
  { role: 'airTemperature', name: /(?:airtemp|mwx.*temp)/i, units: /(?:degc|°c|celsius)/i, description: /air temperature/i },
  { role: 'humidity', name: /(?:humidity|humid|relhum)/i, units: /%|percent/i, description: /humidity/i },
  { role: 'barometer', name: /(?:baropress|baro|barometer)/i, units: /(?:hpa|mbar|pa)/i, description: /barometric|pressure/i },
  { role: 'seaTemperature', name: /(?:tsg.*temp|sst|seatemp)/i, units: /(?:degc|°c|celsius)/i, description: /sea.*temperature|surface temperature/i },
  { role: 'salinity', name: /(?:salinity|sal)/i, units: /(?:psu|ppt)/i, description: /salinity/i },
  { role: 'fluorescence', name: /(?:flr|chl|fluor)/i, units: /(?:ug|µg|mg).*\/?l/i, description: /(?:chlorophyll|fluorescence)/i },
  { role: 'depth', name: /depth/i, units: /(?:m|meter|metre|ft)/i, description: /depth/i },
  { role: 'numeric', name: /$a/, units: /^(?:%|count|deg(?:c|f)?|degree(?:s)?|ft|hpa|hz|knot|kt|m|mbar|mg\/?l|m\/?s|pa|ppt|psu|rpm|ug\/?l|µg\/?l)$/i },
]

export function ruleMatches(rule: RecognitionRule, name: string, details: FieldDescription): boolean {
  if (rule.name.test(name)) return true
  if (rule.units?.test(details.units ?? '') && (!rule.description || rule.description.test(details.description ?? ''))) return true
  return false
}
