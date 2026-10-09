import React from 'react'
import ReactDOM from 'react-dom/client'
import './contentEnv'
import { Root } from './Root.tsx'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
)
