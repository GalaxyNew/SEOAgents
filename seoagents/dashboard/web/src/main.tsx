import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { SeoControlTowerPanel } from './components/SeoControlTowerPanel'
import { LoginGate } from './components/LoginGate'
import { FeedbackProvider } from './ui'
import './index.css'

const publicControlTower = (window.location.hash || '').replace(/^#\/?/, '') === 'gsc_overview'

// Hash 不会到服务端。公开 hash 只挂载 SEO 总控组件，因而不会初始化私有 App、
// 请求 /api/config，或渲染其它 tab；其它 hash 继续经过登录门。
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <FeedbackProvider>
      {publicControlTower ? (
        <SeoControlTowerPanel />
      ) : (
        <LoginGate>
          <App />
        </LoginGate>
      )}
    </FeedbackProvider>
  </React.StrictMode>,
)
