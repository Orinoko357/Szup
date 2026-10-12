import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { ssoExchange } from '../api'
import { syncServerTime } from '../serverTime'

// Powrót z /api/auth/sso-login: jednorazowy kod → token JWT.
// Kod usuwamy z paska adresu od razu (replaceState), żeby nie został w historii.
export default function SsoCallback({ onLogin }) {
  const navigate = useNavigate()
  const done = useRef(false)

  useEffect(() => {
    if (done.current) return
    done.current = true
    const code = new URLSearchParams(window.location.search).get('code')
    window.history.replaceState(null, '', '/sso-callback')
    if (!code) { navigate('/login?sso=error', { replace: true }); return }

    ssoExchange(code).then(async (res) => {
      localStorage.setItem('szup_token', res.data.access_token)
      localStorage.setItem('szup_user', JSON.stringify({
        username:             res.data.username,
        full_name:           res.data.full_name,
        roles:               res.data.roles,
        role:                res.data.role,
        auth_type:           res.data.auth_type,
        must_change_password: false,
      }))
      try { sessionStorage.removeItem('szup_sso_tried') } catch { /* ignore */ }
      await syncServerTime()
      onLogin?.()
      navigate('/', { replace: true })
    }).catch(() => navigate('/login?sso=expired', { replace: true }))
  }, [navigate, onLogin])

  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      height: '100vh', color: 'var(--color-text-muted)', fontSize: 14, gap: 10,
    }}>
      <span className="spinner" style={{ borderTopColor: 'var(--color-gold)', borderColor: 'var(--color-border)' }} />
      Logowanie poświadczeniami Windows…
    </div>
  )
}
