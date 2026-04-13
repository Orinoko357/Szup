import { useState, useEffect } from 'react';
import api from '../../api/axios';

const ROLE_BADGE = { SUPERADMIN: 'badge-purple', IT_ADMIN: 'badge-red', KADRY: 'badge-blue', KIEROWNIK: 'badge-yellow', PRACOWNIK: 'badge-gray' };
const ROLE_OPTIONS = ['PRACOWNIK', 'KIEROWNIK', 'KADRY', 'IT_ADMIN', 'SUPERADMIN'];
const EMPTY = { username: '', imie: '', nazwisko: '', email: '', rola: 'PRACOWNIK', haslo: '' };

export default function AdminUzytkownicy() {
  const [data, setData] = useState([]);
  const [tenants, setTenants] = useState([]);
  const [tenantId, setTenantId] = useState('');
  const [search, setSearch] = useState('');
  const [modal, setModal] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [pwdModal, setPwdModal] = useState(null);
  const [newPwd, setNewPwd] = useState('');

  useEffect(() => { api.get('/tenants').then(r => setTenants(r.data)); }, []);

  const load = () => {
    const p = new URLSearchParams();
    if (tenantId) p.set('tenant_id', tenantId);
    api.get(`/uzytkownicy?${p}`).then(r => setData(r.data));
  };

  useEffect(() => { load(); }, [tenantId]);

  async function submit(e) {
    e.preventDefault(); setSaving(true); setError('');
    try {
      if (modal === 'new') await api.post('/uzytkownicy', form);
      else await api.put(`/uzytkownicy/${modal.id}`, { imie: form.imie, nazwisko: form.nazwisko, email: form.email, rola: form.rola });
      setModal(null); load();
    } catch (e) { setError(e.response?.data?.error || 'Błąd.'); }
    finally { setSaving(false); }
  }

  async function resetPwd() {
    if (!newPwd) return;
    try {
      // Force token revocation + set new password via PUT (if user has one set)
      // Backend doesn't have a dedicated password reset — update via PUT
      await api.put(`/uzytkownicy/${pwdModal}`, { ...(data.find(u => u.id === pwdModal) || {}), haslo: newPwd });
      await api.post(`/uzytkownicy/${pwdModal}/revoke-tokens`);
      setPwdModal(null); setNewPwd('');
      alert('Hasło zmienione, sesje unieważnione.');
    } catch (e) { alert(e.response?.data?.error || 'Błąd.'); }
  }

  async function toggle(id, aktywny) {
    const user = data.find(u => u.id === id);
    if (!user) return;
    await api.put(`/uzytkownicy/${id}`, { ...user, aktywny: !aktywny });
    load();
  }

  async function unlockAccount(id) {
    await api.patch(`/uzytkownicy/${id}/blokada`, { zablokowany: false });
    load();
  }

  const filtered = data.filter(u => !search || u.username.toLowerCase().includes(search.toLowerCase()) || u.imie?.toLowerCase().includes(search.toLowerCase()) || u.nazwisko?.toLowerCase().includes(search.toLowerCase()) || u.email?.toLowerCase().includes(search.toLowerCase()));

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Użytkownicy systemu</h1>
        <button onClick={() => { setForm(EMPTY); setError(''); setModal('new'); }} className="btn-primary">+ Nowy użytkownik</button>
      </div>

      <div className="flex gap-3">
        <input type="text" placeholder="Szukaj (login, imię, email)..." className="border border-gray-300 rounded px-3 py-1.5 text-sm w-72" value={search} onChange={e => setSearch(e.target.value)} />
        <select className="border border-gray-300 rounded px-3 py-1.5 text-sm" value={tenantId} onChange={e => setTenantId(e.target.value)}>
          <option value="">Wszystkie jednostki</option>
          {tenants.map(t => <option key={t.id} value={t.id}>{t.nazwa}</option>)}
        </select>
      </div>

      <div className="card overflow-hidden">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          <thead className="bg-gray-50">
            <tr>{['Login', 'Imię i nazwisko', 'Email', 'Rola', 'Status', 'Ostatnie logowanie', 'Akcje'].map(h => <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-600 uppercase">{h}</th>)}</tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {filtered.map(u => (
              <tr key={u.id} className="hover:bg-gray-50">
                <td className="px-4 py-3 font-mono text-sm">{u.username}</td>
                <td className="px-4 py-3 font-medium">{u.imie} {u.nazwisko}</td>
                <td className="px-4 py-3 text-gray-500">{u.email}</td>
                <td className="px-4 py-3"><span className={ROLE_BADGE[u.rola] || 'badge-gray'}>{u.rola}</span></td>
                <td className="px-4 py-3">
                  {u.zablokowany_do && new Date(u.zablokowany_do) > new Date() ? (
                    <span className="badge-red">Zablokowany</span>
                  ) : u.aktywny !== false ? (
                    <span className="badge-green">Aktywny</span>
                  ) : (
                    <span className="badge-gray">Nieaktywny</span>
                  )}
                </td>
                <td className="px-4 py-3 text-gray-400 text-xs">{u.ostatnie_logowanie ? new Date(u.ostatnie_logowanie).toLocaleString('pl-PL') : '—'}</td>
                <td className="px-4 py-3">
                  <div className="flex gap-2 flex-wrap">
                    <button onClick={() => { setForm({ username: u.username, imie: u.imie || '', nazwisko: u.nazwisko || '', email: u.email || '', rola: u.rola, haslo: '' }); setError(''); setModal(u); }} className="text-xs text-primary-600 hover:underline">Edytuj</button>
                    <button onClick={() => { setPwdModal(u.id); setNewPwd(''); }} className="text-xs text-amber-600 hover:underline">Resetuj hasło</button>
                    {u.zablokowany_do && new Date(u.zablokowany_do) > new Date() && (
                      <button onClick={() => unlockAccount(u.id)} className="text-xs text-green-600 hover:underline">Odblokuj</button>
                    )}
                    <button onClick={() => toggle(u.id, u.aktywny !== false)} className="text-xs text-gray-500 hover:underline">{u.aktywny !== false ? 'Dezakt.' : 'Aktywuj'}</button>
                  </div>
                </td>
              </tr>
            ))}
            {filtered.length === 0 && <tr><td colSpan={7} className="py-8 text-center text-gray-400">Brak użytkowników.</td></tr>}
          </tbody>
        </table>
      </div>

      {/* User modal */}
      {modal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/40" onClick={() => setModal(null)} />
          <div className="relative bg-white rounded-lg shadow-xl p-6 w-full max-w-md space-y-4">
            <h3 className="text-lg font-semibold">{modal === 'new' ? 'Nowy użytkownik' : 'Edytuj użytkownika'}</h3>
            {error && <div className="p-2 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div>}
            <form onSubmit={submit} className="space-y-3">
              {modal === 'new' && (
                <div>
                  <label className="form-label">Login (username) *</label>
                  <input required type="text" className="w-full border border-gray-300 rounded px-3 py-2 text-sm font-mono" value={form.username} onChange={e => setForm({ ...form, username: e.target.value })} />
                </div>
              )}
              <div className="grid grid-cols-2 gap-3">
                <div><label className="form-label">Imię</label><input type="text" className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={form.imie} onChange={e => setForm({ ...form, imie: e.target.value })} /></div>
                <div><label className="form-label">Nazwisko</label><input type="text" className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={form.nazwisko} onChange={e => setForm({ ...form, nazwisko: e.target.value })} /></div>
              </div>
              <div><label className="form-label">Email</label><input type="email" className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={form.email} onChange={e => setForm({ ...form, email: e.target.value })} /></div>
              <div>
                <label className="form-label">Rola</label>
                <select className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={form.rola} onChange={e => setForm({ ...form, rola: e.target.value })}>
                  {ROLE_OPTIONS.map(r => <option key={r} value={r}>{r}</option>)}
                </select>
              </div>
              {modal === 'new' && (
                <div>
                  <label className="form-label">Hasło tymczasowe *</label>
                  <input required type="password" className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={form.haslo} onChange={e => setForm({ ...form, haslo: e.target.value })} placeholder="Min. 8 znaków" />
                </div>
              )}
              <div className="flex gap-3 pt-2">
                <button type="submit" disabled={saving} className="btn-primary">{saving ? 'Zapisywanie...' : 'Zapisz'}</button>
                <button type="button" onClick={() => setModal(null)} className="btn-secondary">Anuluj</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Password reset modal */}
      {pwdModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/40" onClick={() => setPwdModal(null)} />
          <div className="relative bg-white rounded-lg shadow-xl p-6 w-full max-w-sm space-y-4">
            <h3 className="text-lg font-semibold">Reset hasła</h3>
            <div>
              <label className="form-label">Nowe hasło *</label>
              <input type="password" className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={newPwd} onChange={e => setNewPwd(e.target.value)} placeholder="Min. 8 znaków" />
            </div>
            <div className="flex gap-3">
              <button onClick={resetPwd} disabled={!newPwd} className="btn-warning">Zmień hasło</button>
              <button onClick={() => setPwdModal(null)} className="btn-secondary">Anuluj</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
