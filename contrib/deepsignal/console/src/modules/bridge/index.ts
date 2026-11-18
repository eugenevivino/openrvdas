import type { ConsoleModule } from '../../contract'
import { nav, windDial } from './components'
import bridgePreset from './preset.yaml?raw'

const bridge: ConsoleModule = {
  id: 'bridge',
  tiles: [windDial, nav],
  presets: [{ id: 'bridge', yaml: bridgePreset }],
}

export default bridge
