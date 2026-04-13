import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import api from '../../api/axios';

export default function PracownikFormularz() {
  const { id } = useParams();
  const navigate = useNavigate();
  const isNew = !id;

  const [tenants, setTenants] = useState([]);
  const [komorki, setKomorki] = useState([]);
  const [uzytkownicy, setUzytkownicy] = useState([]);
  const [form, setForm] = useState({
    uzytkownik_id: '', tenant_id: '', komorka_id: '', stanowisko: '',
    data_zatrudnienia: '', przelozony_id: '',
  });
  const [userForm, setUserForm] = useState({ username: '', imie: '', nazwisko: '', email: '', rola: 'PRACOWNIK' });
  const [createUser, setCreateUser] = useState(isNew);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.get('/tenants').then(r => setTenants(r.data));
    api.get('/uzytkownicy').then(r => setUzytkownicy(r.data));
    if (!isNew) {
      api.get(`/pracownicy/${id}`).then(r => {
        const p = r.data;
        setForm({
          uzytkownik_id: p.uzytkownik_id,
          tenant_id: p.tenant_id,
          komorka_id: p.komorka_id || '',
          stanowisko: p.stanowisko || '',
          data_zatrudnienia: p.data_zatrudnienia?.split('T')[0] || '',
          przelozony_id: p.przelozony_id || '',
        });
        setCreateUser(false);
      });
    }
  }, [id, isNew]);

  useEffect(() => {
    if (form.tenant_id) {
      api.get(`/komorki?tenant_id=${form.tenant_id}`).then(r => setKomorki(r.data));
    }
  }, [form.tenant_id]);

  async function submit(e) {
    e.preventDefault();
    setError('');
    setSaving(true);
    try {
      let uzytkownikId = form.uzytkownik_id;
      if (createUser) {
        const { data } = await api.post('/uzytkownicy', userForm);
        uzytkownikId = data.id;
      }

      const payload = { ...form, uzytkownik_id: uzytkownikId };
      if (isNew) {
        await api.post('/pracownicy', payload);
      } else {
        await api.put(`/pracownicy/${id}`, payload);
      }
      navigate('/pracownicy');
    } catch (e) {
      setError(e.response?.data?.error || e.response?.data?.errors?.[0]?.msg || 'Błąd zapisu.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="max-w-2xl space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">{isNew ? 'Nowy pracownik' : 'Edytuj pracownika'}</h1>
      {error && <div className="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div>}

      <form onSubmit={submit} className="space-y-6">
        {isNew && (
          <div className="card p-5 space-y-4">
            <div className="flex items-center gap-3">
              <h2 className="font-semibold">Konto użytkownika</h2>
              <label className="flex items-center gap-2 text-sm ml-auto">
                <input type="checkbox" checked={createUser} onChange={e => setCreateUser(e.target.checked)} className="rounded" />
                Utwórz nowe konto
              </label>
            </div>
            {createUser ? (
              <div className="grid grid-cols-2 gap-3">
                {[
                  ['username', 'Nazwa użytkownika *'], ['imie', 'Imię *'], ['nazwisko', 'Nazwisko *'], ['email', 'Email *'],
                ].map(([field, label]) => (
                  <div key={field}>
                    <label className="form-label">{label}</label>
                    <input type={field === 'email' ? 'email' : 'text'} required className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:outline-none" value={userForm[field]} onChange={e => setUserForm({ ...userForm, [field]: e.target.value })} />
                  </div>
                ))}
                <div>
                  <label className="form-label">Rola</label>
                  <select className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:outline-none" value={userForm.rola} onChange={e => setUserForm({ ...userForm, rola: e.target.value })}>
                    {['PRACOWNIK', 'KIEROWNIK', 'KADRY', 'IT_ADMIN'].map(r => <option key={r} value={r}>{r}</option>)}
                  </select>
                </div>
              </div>
            ) : (
              <div>
                <label className="form-label">Wybierz istniejące konto</label>
                <select className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:outline-none" value={form.uzytkownik_id} onChange={e => setForm({ ...form, uzytkownik_id: e.target.value })}>
                  <option value="">-- Wybierz --</option>
                  {uzytkownicy.map(u => <option key={u.id} value={u.id}>{u.imie} {u.nazwisko} ({u.username})</option>)}
                </select>
              </div>
            )}
          </div>
        )}

        <div className="card p-5 space-y-4">
          <h2 className="font-semibold">Dane kadrowe</h2>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="form-label">Jednostka *</label>
              <select required className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:outline-none" value={form.tenant_id} onChange={e => setForm({ ...form, tenant_id: e.target.value, komorka_id: '' })}>
                <option value="">-- Wybierz --</option>
                {tenants.map(t => <option key={t.id} value={t.id}>{t.nazwa}</option>)}
              </select>
            </div>
            <div>
              <label className="form-label">Komórka organizacyjna</label>
              <select className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:outline-none" value={form.komorka_id} onChange={e => setForm({ ...form, komorka_id: e.target.value })}>
                <option value="">-- Brak --</option>
                {komorki.map(k => <option key={k.id} value={k.id}>{k.nazwa}</option>)}
              </select>
            </div>
            <div>
              <label className="form-label">Stanowisko</label>
              <input type="text" className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:outline-none" value={form.stanowisko} onChange={e => setForm({ ...form, stanowisko: e.target.value })} />
            </div>
            <div>
              <label className="form-label">Data zatrudnienia</label>
              <input type="date" className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:outline-none" value={form.data_zatrudnienia} onChange={e => setForm({ ...form, data_zatrudnienia: e.target.value })} />
            </div>
          </div>
        </div>

        <div className="flex gap-3">
          <button type="submit" disabled={saving} className="btn-primary">{saving ? 'Zapisywanie...' : 'Zapisz'}</button>
          <button type="button" onClick={() => navigate(-1)} className="btn-secondary">Anuluj</button>
        </div>
      </form>
    </div>
  );
}
