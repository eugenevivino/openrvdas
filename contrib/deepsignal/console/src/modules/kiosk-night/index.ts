import type { ConsoleModule } from '../../contract'
import { startAutoNight } from './autoNight'
import { KioskSlot } from './kiosk'

const kioskNight: ConsoleModule = {
  id: 'kiosk-night',
  engines: [{ id: 'kiosk-night-auto', start: startAutoNight }],
  slots: [{ slot: 'topbar', order: 90, Component: KioskSlot }],
}

export default kioskNight
