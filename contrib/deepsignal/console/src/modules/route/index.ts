import type { ConsoleModule, TileDef } from '../../contract'
import { RouteTile } from './RouteTile'

const examples = {
  lat: 'S330Latitude', lon: 'S330Longitude', cog: 'S330CourseTrue', sog: 'S330SpeedKt', route: 'routes.json',
}

const tile: TileDef = {
  type: 'route',
  validate(raw, where) {
    for (const [setting, example] of Object.entries(examples)) {
      const value = raw[setting]
      if (setting === 'route' && value === undefined) continue
      if (typeof value !== 'string' || !value.trim()) {
        throw { where, setting, saw: String(value), expected: setting === 'route' ? 'a file name' : 'a field name', example }
      }
    }
    return { ...raw, type: 'route', route: raw.route ?? examples.route }
  },
  fields: cfg => [String(cfg.lat), String(cfg.lon), String(cfg.cog), String(cfg.sog)],
  Component: RouteTile,
}

export default { id: 'route', tiles: [tile] } satisfies ConsoleModule
