import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../../api/axios';
import { useAuth } from '../../hooks/useAuth';

export default function Login() {
  const { login, user } = useAuth();
  const navigate = useNavigate();
  const [domains, setDomains] = useState([]);
  const [form, setForm] = useState({ username: '', password: '', domena_id: '' });
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
      setError(err.response?.data?.error || 'Błąd logowania.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-primary-900 to-primary-700 flex items-center justify-center px-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md p-8">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 bg-primary-600 rounded-2xl mb-4">
            <span className="text-white font-bold text-xl">ZUP</span>
          </div>
          <h1 className="text-2xl font-bold text-gray-900">System ZUP</h1>
          <p className="text-sm text-gray-500 mt-1">Zarządzanie Uprawnieniami w Systemach Teleinformatycznych</p>
        </div>

        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="form-label">Nazwa użytkownika</label>
            <input
              type="text"
              className="form-input border px-3 py-2 w-full rounded-md border-gray-300 focus:outline-none focus:ring-2 focus:ring-primary-500"
              value={form.username}
              onChange={e => setForm({ ...form, username: e.target.value })}
              autoComplete="username"
              required
            />
          </div>
          <div>
            <label className="form-label">Hasło</label>
            <input
              type="password"
              className="form-input border px-3 py-2 w-full rounded-md border-gray-300 focus:outline-none focus:ring-2 focus:ring-primary-500"
              value={form.password}
              onChange={e => setForm({ ...form, password: e.target.value })}
              autoComplete="current-password"
              required
            />
          </div>
          <div>
            <label className="form-label">Domena</label>
            <select
              className="form-input border px-3 py-2 w-full rounded-md border-gray-300 focus:outline-none focus:ring-2 focus:ring-primary-500"
              value={form.domena_id}
              onChange={e => setForm({ ...form, domena_id: e.target.value })}
            >
              <option value="__auto__">Wykryj automatycznie</option>
              {domains.map(d => (
                <option key={d.id} value={d.id}>{d.nazwa} ({d.domena})</option>
              ))}
              <option value="__local__">Administrator lokalny</option>
            </select>
          </div>
          <button
            type="submit"
            disabled={loading}
            className="btn-primary w-full py-2.5 mt-2"
          >
            {loading ? 'Logowanie...' : 'Zaloguj się'}
          </button>
        </form>

        <p className="text-center text-xs text-gray-400 mt-6">
          NIS2 art. 21 | Zgodność z ustawą o samorządzie gminnym art. 10a
        </p>
      </div>
    </div>
  );
}
