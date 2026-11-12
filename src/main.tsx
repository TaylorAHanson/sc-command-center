import React from 'react'
import ReactDOM from 'react-dom/client'
import { stripLegacyEnvParam } from './contentEnv'
import { takeOAuthOutcome } from './schedules'
import { Root } from './Root.tsx'
import './index.css'

// Before anything reads the address, so no link built from it carries the old workspace.
stripLegacyEnvParam()
// Likewise the outcome of connecting an account, which is shown once and not kept in links.
takeOAuthOutcome()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
)
