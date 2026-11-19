import type { ConsoleModule } from '../../contract'
import { SelfTest } from './SelfTest'

const selfTestModule: ConsoleModule = {
  id: 'self-test',
  routes: [{
    id: 'self-test',
    title: 'Self-test',
    order: 95,
    Component: SelfTest,
    fields: (ctx) => [...new Set([
      ...ctx.store.listFields(), 'status:logger_status', 'status:cruise_mode',
    ])],
  }],
}

export default selfTestModule
