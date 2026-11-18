import { createRoot } from 'react-dom/client'
import '@fontsource/barlow/latin-400.css'
import '@fontsource/barlow-semi-condensed/latin-600.css'
import '@fontsource/ibm-plex-mono/latin-400.css'
import './index.css'
import App from './App'

createRoot(document.getElementById('root')!).render(<App />)
