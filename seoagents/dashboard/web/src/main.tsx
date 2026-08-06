import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { LoginGate } from './components/LoginGate'
import { FeedbackProvider } from './ui'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <FeedbackProvider>
      <LoginGate>
        <App />
      </LoginGate>
    </FeedbackProvider>
  </React.StrictMode>,
)
