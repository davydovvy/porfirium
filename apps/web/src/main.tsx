import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import { initializeAuth } from './auth'
import './styles.css'

const root = createRoot(document.getElementById('root')!)

initializeAuth()
  .then((authenticated) => root.render(<StrictMode><App authenticated={authenticated} /></StrictMode>))
  .catch((error: Error) => root.render(<div className="fatal">Authentication initialization failed: {error.message}</div>))
