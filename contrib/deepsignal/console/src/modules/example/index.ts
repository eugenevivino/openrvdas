import type { ConsoleModule } from '../../contract'
import yaml from './example.yaml?raw'

export default { id: 'example', presets: [{ id: 'example', yaml }] } satisfies ConsoleModule
