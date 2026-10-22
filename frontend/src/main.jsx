import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles/theme.css'
import App from './App'
import { FeedbackHost } from './components/ui/feedback'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
    <FeedbackHost />
  </StrictMode>
)
