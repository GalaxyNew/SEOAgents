import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { LoginGate } from './components/LoginGate'
import './index.css'

// 登录门包在最外层:App 内部所有请求都假定已经登录,
// 在这里挡住比让每个面板各自处理 401 要可靠得多。
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <LoginGate>
      <App />
    </LoginGate>
  </React.StrictMode>,
)
