import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import DebugPage from './DebugPage.tsx'

const path = window.location.pathname.replace(/\/$/, '') || '/'
const page = path === '/debug' ? <DebugPage /> : <App />

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {page}
  </StrictMode>,
)
