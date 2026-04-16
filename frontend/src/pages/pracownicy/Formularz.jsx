import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import api from '../../api/axios';

const EMPTY_FORM = {
  uzytkownik_id: '', tenant_id: '', jednostka_id: '', stanowisko: '',
  imie: '', nazwisko: '', email: '',
  data_zatrudnienia: '', przelozony_id: '',
};
const EMPTY_USER = { username: '', imie: '', nazwisko: '', email: '', rola: 'PRACOWNIK' };

// accountMode: 'new' | 'existing' | 'none'
export default function PracownikFormularz() {
  const { id } = useParams();
  const navigate = useNavigate();
  const isNew = !id;

  const [tenants, setTenants]       = useState([]);
  const [jednostki, setJednostki]   = useState([]);
  const [uzytkownicy, setUzytkownicy] = useState([]);
  const [pracownicy, setPracownicy]  = useState([]);
  const [form, setForm]             = useState(EMPTY_FORM);
  const [userForm, setUserForm]     = useState(EMPTY_USER);
  const [accountMode, setAccountMode] = useState('new'); // for new records
  const [error, setError]           = useState('');
  const [saving, setSaving]         = useState(false);

  useEffect(() => {
    api.get('/tenants').then(r => setTenants(r.data));
    api.get('/uzytkownicy').then(r => setUzytkownicy(r.data));
    if (!isNew) {
      api.get(`/pracownicy/${id}`).then(r => {
        const p = r.data;
        setForm({
          uzytkownik_id: p.uzytkownik_id || '',
          tenant_id: p.tenant_id,
          jednostka_id: p.jednostka_id || '',
          stanowisko: p.stanowisko || '',
          imie: p.imie || '',
          nazwisko: p.nazwisko || '',
          email: p.email || '',
          data_zatrudnienia: p.data_zatrudnienia?.split('T')[0] || '',
          przelozony_id: p.przelozony_id || '',
        });
        setAccountMode(p.uzytkownik_id ? 'existing' : 'none');
      });
    }
  }, [id, isNew]);

  useEffect(() => {
    if (form.tenant_id) {
      api.get(`/jednostki-org?tenant_id=${form.tenant_id}`).then(r => setJednostki(r.data));
      api.get(`/pracownicy?tenant_id=${form.tenant_id}&aktywny=true`).then(r => setPracownicy(r.data));
    }
  }, [form.tenant_id]);

  async function submit(e) {
    e.preventDefault();
    setError('');
    setSaving(true);
    try {
      let uzytkownikId = form.uzytkownik_id || null;
      let imie = form.imie || null;
      let nazwisko = form.nazwisko || null;
      let email = form.email || null;

      if (isNew && accountMode === 'new') {
        const { data } = await api.post('/uzytkownicy', userForm);
        uzytkownikId = data.id;
        imie = null; nazwisko = null; email = null; // stored on user record
      } else if (accountMode === 'existing') {
        imie = null; nazwisko = null; email = null;
      }
      // accountMode === 'none' → uzytkownikId stays null, imie/nazwisko from form

      const payload = {
        ...form,
        uzytkownik_id: uzytkownikId || null,
        imie, nazwisko, email,
        tenant_id: Number(form.tenant_id),
        jednostka_id: form.jednostka_id ? Number(form.jednostka_id) : null,
        przelozony_id: form.przelozony_id ? Number(form.przelozony_id) : null,
      };

      if (isNew) {
        await api.post('/pracownicy', payload);
      } else {
        await api.put(`/pracownicy/${id}`, payload);
      }
      navigate('/pracownicy');
    } catch (err) {
      setError(err.response?.data?.detail || err.response?.data?.error || 'Błąd zapisu.');
    } finally {
      setSaving(false);
    }
  }

  const f = (field, val) => setForm(prev => ({ ...prev, [field]: val }));

  return (
    <div className="max-w-2xl space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">{isNew ? 'Nowy pracownik' : 'Edytuj pracownika'}</h1>
      {error && <div className="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div>}

      <form onSubmit={submit} className="space-y-6">

        {/* === KONTO UŻYTKOWNIKA === */}
        <div className="card p-5 space-y-4">
          <h2 className="font-semibold">Konto użytkownika</h2>

          {isNew && (
            <div className="flex gap-4 text-sm">
              {[
                ['new',      'Utwórz nowe konto'],
                ['existing', 'Powiąż istniejące'],
                ['none',     'Bez konta w systemie'],
              ].map(([mode, label]) => (
                <label key={mode} className="flex items-center gap-1.5 cursor-pointer">
                  <input type="radio" name="accountMode" value={mode}
                    checked={accountMode === mode}
                    onChange={() => setAccountMode(mode)} />
                  {label}
                </label>
              ))}
            </div>
          )}

          {isNew && accountMode === 'new' && (
            <div className="grid grid-cols-2 gap-3">
              {[
                ['username', 'Nazwa użytkownika *', 'text'],
                ['imie',     'Imię *',              'text'],
                ['nazwisko', 'Nazwisko *',          'text'],
                ['email',    'Email *',             'email'],
              ].map(([field, label, type]) => (
                <div key={field}>
                  <label className="form-label">{label}</label>
                  <input type={type} required
                    className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:outline-none"
                    value={userForm[field]}
                    onChange={e => setUserForm({ ...userForm, [field]: e.target.value })} />
                </div>
              ))}
              <div>
                <label className="form-label">Rola</label>
                <select className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:outline-none"
                  value={userForm.rola}
                  onChange={e => setUserForm({ ...userForm, rola: e.target.value })}>
                  {['PRACOWNIK', 'KIEROWNIK', 'KADRY', 'IT_ADMIN'].map(r => (
                    <option key={r} value={r}>{r}</option>
                  ))}
                </select>
              </div>
            </div>
          )}

          {(accountMode === 'existing' || (!isNew && form.uzytkownik_id)) && (
            <div>
              <label className="form-label">Konto użytkownika</label>
              <select className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:outline-none"
                value={form.uzytkownik_id}
                onChange={e => f('uzytkownik_id', e.target.value)}>
                <option value="">-- Wybierz --</option>
                {uzytkownicy.map(u => (
                  <option key={u.id} value={u.id}>{u.imie} {u.nazwisko} ({u.username})</option>
                ))}
              </select>
            </div>
          )}

          {(isNew ? accountMode === 'none' : !form.uzytkownik_id) && (
            <div className="grid grid-cols-2 gap-3">
              <p className="col-span-2 text-xs text-gray-500">Pracownik bez konta — podaj dane do wyświetlania:</p>
              <div>
                <label className="form-label">Imię *</label>
                <input type="text" required
                  className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:outline-none"
                  value={form.imie} onChange={e => f('imie', e.target.value)} />
              </div>
              <div>
                <label className="form-label">Nazwisko *</label>
                <input type="text" required
                  className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:outline-none"
                  value={form.nazwisko} onChange={e => f('nazwisko', e.target.value)} />
              </div>
              <div className="col-span-2">
                <label className="form-label">Email</label>
                <input type="email"
                  className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:outline-none"
                  value={form.email} onChange={e => f('email', e.target.value)} />
              </div>
            </div>
          )}
        </div>

        {/* === DANE KADROWE === */}
        <div className="card p-5 space-y-4">
          <h2 className="font-semibold">Dane kadrowe</h2>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="form-label">Urząd / Instytucja *</label>
              <select required
                className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:outline-none"
                value={form.tenant_id}
                onChange={e => setForm(prev => ({ ...prev, tenant_id: e.target.value, jednostka_id: '' }))}>
                <option value="">-- Wybierz --</option>
                {tenants.map(t => <option key={t.id} value={t.id}>{t.nazwa}</option>)}
              </select>
            </div>
            <div>
              <label className="form-label">Komórka / Wydział</label>
              <select
                className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:outline-none"
                value={form.jednostka_id}
                onChange={e => f('jednostka_id', e.target.value)}>
                <option value="">-- Brak --</option>
                {jednostki.map(j => (
                  <option key={j.id} value={j.id}>
                    {j.typ === 'URZAD' ? '' : j.typ === 'WYDZIAL' ? '  ' : '    '}{j.nazwa}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="form-label">Stanowisko</label>
              <input type="text"
                className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:outline-none"
                value={form.stanowisko} onChange={e => f('stanowisko', e.target.value)} />
            </div>
            <div>
              <label className="form-label">Data zatrudnienia</label>
              <input type="date"
                className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:outline-none"
                value={form.data_zatrudnienia} onChange={e => f('data_zatrudnienia', e.target.value)} />
            </div>
            <div className="col-span-2">
              <label className="form-label">Przełożony</label>
              <select
                className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:outline-none"
                value={form.przelozony_id}
                onChange={e => f('przelozony_id', e.target.value)}>
                <option value="">-- Brak --</option>
                {pracownicy
                  .filter(p => String(p.id) !== String(id))
                  .map(p => (
                    <option key={p.id} value={p.id}>
                      {p.imie} {p.nazwisko}{p.stanowisko ? ` — ${p.stanowisko}` : ''}
                    </option>
                  ))}
              </select>
            </div>
          </div>
        </div>

        <div className="flex gap-3">
          <button type="submit" disabled={saving} className="btn-primary">
            {saving ? 'Zapisywanie...' : 'Zapisz'}
          </button>
          <button type="button" onClick={() => navigate(-1)} className="btn-secondary">Anuluj</button>
        </div>
      </form>
    </div>
  );
}
