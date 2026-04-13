import { useState, useEffect } from 'react';
import api from '../../api/axios';

const EMPTY = {
  nazwa: '', domena: '', ldap_url: '', base_dn: '', bind_dn: '', bind_password: '',
  user_filter: '(&(objectClass=user)(sAMAccountName=%s))', tls: true, aktywna: true, kolejnosc: 10,
  attr_email: 'mail', attr_firstname: 'givenName', attr_lastname: 'sn', attr_username: 'sAMAccountName',
};

export default function AdminLdapDomeny() {
  const [data, setData] = useState([]);
  const [modal, setModal] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [testing, setTesting] = useState(null);
  const [testResult, setTestResult] = useState({});
  const [advanced, setAdvanced] = useState(false);

  const load = () => api.get('/ldap-domeny').then(r => setData(r.data));
  useEffect(() => { load(); }, []);

  function openNew() { setForm(EMPTY); setError(''); setAdvanced(false); setModal('new'); }
  function openEdit(d) {
    setForm({
      nazwa: d.nazwa, domena: d.domena || '', ldap_url: d.ldap_url, base_dn: d.base_dn,
      bind_dn: d.bind_dn, bind_password: '',
      user_filter: d.user_filter || '', tls: d.tls, aktywna: d.aktywna, kolejnosc: d.kolejnosc,
      attr_email: d.attr_email || 'mail', attr_firstname: d.attr_firstname || 'givenName',
      attr_lastname: d.attr_lastname || 'sn', attr_username: d.attr_username || 'sAMAccountName',
    });
    setError(''); setAdvanced(false); setModal(d);
  }

  async function submit(e) {
    e.preventDefault();
    setSaving(true); setError('');
    try {
      if (modal === 'new') {
        await api.post('/ldap-domeny', form);
      } else {
        await api.put(`/ldap-domeny/${modal.id}`, form);
      }
      setModal(null); load();
    } catch (e) { setError(e.response?.data?.error || 'Błąd.'); }
    finally { setSaving(false); }
  }

  async function testConn(id) {
    setTesting(id);
    try {
      const r = await api.post(`/ldap-domeny/${id}/test`);
      setTestResult({ [id]: { ok: true, msg: r.data.message || 'Połączenie OK' } });
    } catch (e) {
      setTestResult({ [id]: { ok: false, msg: e.response?.data?.message || 'Błąd połączenia' } });
    } finally { setTesting(null); }
  }

  async function remove(id) {
    if (!confirm('Usunąć domenę LDAP?')) return;
    await api.delete(`/ldap-domeny/${id}`);
    load();
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Domeny LDAP / Active Directory</h1>
        <button onClick={openNew} className="btn-primary">+ Nowa domena</button>
      </div>

      <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-sm text-blue-800">
        Hasło service account jest przechowywane w postaci zaszyfrowanej (AES-256-GCM) i nigdy nie jest zwracane przez API.
      </div>

      <div className="space-y-3">
        {data.map(d => (
          <div key={d.id} className="card p-4">
            <div className="flex items-start justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-semibold">{d.nazwa}</span>
                  {d.aktywna ? <span className="badge-green">Aktywna</span> : <span className="badge-gray">Nieaktywna</span>}
                  <span className="text-xs text-gray-400">kolejność: {d.kolejnosc}</span>
                </div>
                <div className="text-sm text-gray-500 mt-1">{d.ldap_url}</div>
                <div className="text-xs text-gray-400 mt-0.5">Base DN: {d.base_dn}</div>
                <div className="text-xs text-gray-400">Bind DN: {d.bind_dn}</div>
              </div>
              <div className="flex gap-2 items-center flex-wrap justify-end">
                {testResult[d.id] && (
                  <span className={`text-xs ${testResult[d.id].ok ? 'text-green-600' : 'text-red-600'}`}>{testResult[d.id].msg}</span>
                )}
                <button onClick={() => testConn(d.id)} disabled={testing === d.id} className="btn-secondary btn-sm">{testing === d.id ? 'Testuję...' : 'Test'}</button>
                <button onClick={() => openEdit(d)} className="btn-secondary btn-sm">Edytuj</button>
                <button onClick={() => remove(d.id)} className="text-xs text-red-600 hover:underline">Usuń</button>
              </div>
            </div>
          </div>
        ))}
        {data.length === 0 && <div className="card p-8 text-center text-gray-400">Brak skonfigurowanych domen LDAP.</div>}
      </div>

      {modal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto py-8">
          <div className="absolute inset-0 bg-black/40" onClick={() => setModal(null)} />
          <div className="relative bg-white rounded-lg shadow-xl p-6 w-full max-w-lg space-y-4">
            <h3 className="text-lg font-semibold">{modal === 'new' ? 'Nowa domena LDAP' : 'Edytuj domenę'}</h3>
            {error && <div className="p-2 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div>}
            <form onSubmit={submit} className="space-y-3">
              <div>
                <label className="form-label">Nazwa wyświetlana *</label>
                <input required type="text" className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={form.nazwa} onChange={e => setForm({ ...form, nazwa: e.target.value })} placeholder="np. Urząd Miejski AD" />
              </div>
              <div>
                <label className="form-label">Nazwa domeny (NetBIOS/DNS)</label>
                <input type="text" className="w-full border border-gray-300 rounded px-3 py-2 text-sm font-mono" value={form.domena} onChange={e => setForm({ ...form, domena: e.target.value })} placeholder="np. EXAMPLE lub example.local" />
              </div>
              <div>
                <label className="form-label">LDAP URL *</label>
                <input required type="text" className="w-full border border-gray-300 rounded px-3 py-2 text-sm font-mono text-xs" value={form.ldap_url} onChange={e => setForm({ ...form, ldap_url: e.target.value })} placeholder="ldaps://dc.example.local:636" />
              </div>
              <div className="flex items-center gap-3">
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={form.tls} onChange={e => setForm({ ...form, tls: e.target.checked })} className="rounded" />
                  Wymuś TLS/SSL
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={form.aktywna} onChange={e => setForm({ ...form, aktywna: e.target.checked })} className="rounded" />
                  Domena aktywna
                </label>
              </div>
              <div>
                <label className="form-label">Base DN *</label>
                <input required type="text" className="w-full border border-gray-300 rounded px-3 py-2 text-sm font-mono text-xs" value={form.base_dn} onChange={e => setForm({ ...form, base_dn: e.target.value })} placeholder="DC=example,DC=local" />
              </div>
              <div>
                <label className="form-label">Bind DN (service account) *</label>
                <input required type="text" className="w-full border border-gray-300 rounded px-3 py-2 text-sm font-mono text-xs" value={form.bind_dn} onChange={e => setForm({ ...form, bind_dn: e.target.value })} placeholder="CN=svc-ldap,OU=Accounts,DC=example,DC=local" />
              </div>
              <div>
                <label className="form-label">Hasło service account {modal !== 'new' && <span className="text-gray-400">(puste = bez zmian)</span>}</label>
                <input type="password" autoComplete="new-password" className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={form.bind_password} onChange={e => setForm({ ...form, bind_password: e.target.value })} />
              </div>
              <div>
                <label className="form-label">Filtr użytkownika</label>
                <input type="text" className="w-full border border-gray-300 rounded px-3 py-2 text-sm font-mono text-xs" value={form.user_filter} onChange={e => setForm({ ...form, user_filter: e.target.value })} />
              </div>
              <div>
                <label className="form-label">Kolejność (niższy = wyższy priorytet)</label>
                <input type="number" className="w-32 border border-gray-300 rounded px-3 py-2 text-sm" value={form.kolejnosc} onChange={e => setForm({ ...form, kolejnosc: Number(e.target.value) })} />
              </div>

              <div>
                <button type="button" onClick={() => setAdvanced(!advanced)} className="text-sm text-primary-600 hover:underline">
                  {advanced ? '▲ Ukryj' : '▼ Pokaż'} zaawansowane (atrybuty LDAP)
                </button>
              </div>
              {advanced && (
                <div className="grid grid-cols-2 gap-3 p-3 bg-gray-50 rounded">
                  {[['attr_username', 'Atrybut loginu'], ['attr_email', 'Atrybut email'], ['attr_firstname', 'Atrybut imienia'], ['attr_lastname', 'Atrybut nazwiska']].map(([f, l]) => (
                    <div key={f}>
                      <label className="form-label">{l}</label>
                      <input type="text" className="w-full border border-gray-300 rounded px-3 py-2 text-sm font-mono text-xs" value={form[f]} onChange={e => setForm({ ...form, [f]: e.target.value })} />
                    </div>
                  ))}
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
    </div>
  );
}
