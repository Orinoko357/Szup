import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../../api/axios';
import { useAuth } from '../../hooks/useAuth';
import { Shield, User, Lock, ChevronDown } from 'lucide-react';

export default function Login() {
  const { login, user } = useAuth();
  const navigate = useNavigate();
  const [domains, setDomains] = useState([]);
  const [form, setForm] = useState({ username: '', password: '', domena_id: '__local__' });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (user) navigate('/');
    api.get('/auth/ldap-domains').then(r => setDomains(r.data)).catch(() => {});
  }, [user, navigate]);

  const isLocal = form.domena_id === '__local__';

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const endpoint = isLocal ? '/auth/login' : '/auth/ldap-login';
      const payload = { username: form.username, password: form.password };
      if (!isLocal && form.domena_id && form.domena_id !== '__auto__') {
        payload.domena_id = parseInt(form.domena_id);
      }
      const { data } = await api.post(endpoint, payload);
      login(data.accessToken, data.user);
      navigate('/');
    } catch (err) {
      setError(err.response?.data?.error || 'Nieprawidłowe dane logowania.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ minHeight: '100vh', background: 'linear-gradient(135deg, #0e1f38 0%, #1c355e 50%, #24406d 100%)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '16px' }}>
      <div style={{ width: '100%', maxWidth: '420px' }}>
        {/* Logo */}
        <div style={{ textAlign: 'center', marginBottom: '32px' }}>
          <div style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: '64px', height: '64px', background: '#c5a065', borderRadius: '16px', marginBottom: '16px' }}>
            <Shield size={32} color="#1c355e" strokeWidth={2.5} />
          </div>
          <div style={{ color: 'white', fontSize: '22px', fontWeight: '800', letterSpacing: '-0.3px' }}>SZUP</div>
          <div style={{ color: 'rgba(255,255,255,0.5)', fontSize: '13px', marginTop: '4px' }}>
            System Zarządzania Uprawnieniami
          </div>
        </div>

        {/* Card */}
        <div style={{ background: 'white', borderRadius: '12px', padding: '32px', boxShadow: '0 20px 60px rgba(0,0,0,0.3)' }}>
          <div style={{ marginBottom: '24px' }}>
            <div style={{ fontSize: '11px', fontWeight: '700', textTransform: 'uppercase', letterSpacing: '0.08em', color: '#6b7280', borderLeft: '4px solid #c5a065', paddingLeft: '10px' }}>
              Logowanie do systemu
            </div>
          </div>

          {error && (
            <div style={{ marginBottom: '16px', padding: '10px 14px', background: '#fee2e2', border: '1px solid #fca5a5', borderRadius: '6px', color: '#991b1b', fontSize: '13px' }}>
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div>
              <label className="form-label">Nazwa użytkownika</label>
              <div style={{ position: 'relative' }}>
                <User size={15} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: '#9ca3af' }} />
                <input
                  type="text"
                  className="form-input"
                  style={{ paddingLeft: '36px' }}
                  value={form.username}
                  onChange={e => setForm({ ...form, username: e.target.value })}
                  autoComplete="username"
                  required
                  placeholder="login"
                />
              </div>
            </div>

            <div>
              <label className="form-label">Hasło</label>
              <div style={{ position: 'relative' }}>
                <Lock size={15} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: '#9ca3af' }} />
                <input
                  type="password"
                  className="form-input"
                  style={{ paddingLeft: '36px' }}
                  value={form.password}
                  onChange={e => setForm({ ...form, password: e.target.value })}
                  autoComplete="current-password"
                  required
                  placeholder="••••••••"
                />
              </div>
            </div>

            <div>
              <label className="form-label">Metoda uwierzytelnienia</label>
              <div style={{ position: 'relative' }}>
                <select
                  className="form-input"
                  style={{ appearance: 'none', paddingRight: '32px' }}
                  value={form.domena_id}
                  onChange={e => setForm({ ...form, domena_id: e.target.value })}
                >
                  <option value="__local__">Administrator lokalny</option>
                  {domains.map(d => (
                    <option key={d.id} value={d.id}>{d.nazwa} ({d.domena})</option>
                  ))}
                  {domains.length > 0 && <option value="__auto__">Wykryj automatycznie</option>}
                </select>
                <ChevronDown size={14} style={{ position: 'absolute', right: '12px', top: '50%', transform: 'translateY(-50%)', color: '#9ca3af', pointerEvents: 'none' }} />
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="btn btn-primary"
              style={{ width: '100%', padding: '11px 16px', marginTop: '4px', fontSize: '14px' }}
            >
              {loading ? 'Logowanie...' : 'Zaloguj się'}
            </button>
          </form>
        </div>

        <p style={{ textAlign: 'center', color: 'rgba(255,255,255,0.25)', fontSize: '11px', marginTop: '20px' }}>
          NIS2 art. 21 · Ustawa o samorządzie gminnym art. 10a
        </p>
      </div>
    </div>
  );
}
