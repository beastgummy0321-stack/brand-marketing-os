import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './styles/tokens.css'
import App from './App.tsx'

// basename="/app"：production 掛載於 /app（app/main.py），開發模式 vite.config.ts
// 的 base 也設 '/app/'，兩邊路徑片段行為一致（票 05-spa-routing）。
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter basename="/app">
      <App />
    </BrowserRouter>
  </StrictMode>,
)
