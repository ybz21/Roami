import React from 'react'
import { createRoot } from '../../../../frontend/node_modules/react-dom/client'
import { useLayout } from '../../../../frontend/src/layout'
import './application.js'
function LayoutObserver() { useLayout(); return null }
createRoot(document.getElementById('layout-observer')!).render(<LayoutObserver />)
