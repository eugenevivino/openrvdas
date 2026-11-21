import type { ConsoleContext, ConsoleModule } from '../../contract'
import { createElement } from 'react'
import { WorkspacePage } from './page'
import type { View } from './page'

function route(view: View) {
  return ({ ctx }: { ctx: ConsoleContext }) => createElement(WorkspacePage, { ctx, view })
}

const workspace: ConsoleModule = {
  id: 'workspace',
  routes: [
    { id: 'workspace-explorer', title: 'Data Explorer', order: 40, Component: route('explorer') },
    { id: 'workspace-configuration', title: 'Configuration Workbench', order: 41, Component: route('configuration') },
    { id: 'workspace-investigations', title: 'Investigations', order: 42, Component: route('investigations') },
    { id: 'workspace-connections', title: 'Connections', order: 43, Component: route('connections') },
  ],
}
export default workspace
