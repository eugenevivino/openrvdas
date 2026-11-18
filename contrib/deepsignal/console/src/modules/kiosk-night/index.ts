import type { ConsoleModule } from '../../contract'
import { positionFields, startAutoNight } from './autoNight'
import { KioskSlot } from './kiosk'

const kioskNight: ConsoleModule = {
  id: 'kiosk-night',
  engines: [{ id: 'kiosk-night-auto', start: startAutoNight }],
  adapters: [{ id: 'kiosk-night-position', fields: positionFields, onValue: () => undefined }],
  slots: [{ slot: 'topbar', order: 90, Component: KioskSlot }],
}

export default kioskNight
