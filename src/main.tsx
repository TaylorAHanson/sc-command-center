import React from 'react'
import ReactDOM from 'react-dom/client'
import { stripLegacyEnvParam } from './contentEnv'
import { Root } from './Root.tsx'
import './index.css'

// Before anything reads the address, so no link built from it carries the old workspace.
stripLegacyEnvParam()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
)
