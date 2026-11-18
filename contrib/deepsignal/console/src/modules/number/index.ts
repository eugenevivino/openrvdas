import type { ConsoleModule } from '../../contract'
import { NumberTile } from './NumberTile'
import { validateNumber } from './validate'
import type { NumberTileConfig } from './validate'

export default {
  id: 'number',
  tiles: [{
    type: 'number',
    validate: validateNumber,
    fields: (cfg) => [(cfg as NumberTileConfig).field],
    Component: NumberTile,
  }],
} satisfies ConsoleModule
