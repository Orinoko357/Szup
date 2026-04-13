import { useState, useEffect } from 'react';
import api from '../../api/axios';

export default function PrzypisaniaSzablonow() {
  const [tenants, setTenants] = useState([]);
  const [tenantId, setTenantId] = useState('');
  const [szablony, setSzablony] = useState([]);
  const [komorki, setKomorki] = useState([]);
  const [przypisania, setPrzypisania] = useState([]);
  const [defaultSzablon, setDefaultSzablon] = useState('');
  const [saving, setSaving] = useState({});
  const [msg, setMsg] = useState('');

  useEffect(() => { api.get('/tenants').then(r => setTenants(r.data)); }, []);

  useEffect(() => {
    if (!tenantId) return;
    Promise.all([
      api.get(`/workflow/szablony?tenant_id=${tenantId}`),
      api.get(`/komorki?tenant_id=${tenantId}`),
      api.get(`/workflow/przypisania?tenant_id=${tenantId}`),
    ]).then(([s, k, p]) => {
      setSzablony(s.data);
      setKomorki(k.data);
      setPrzypisania(p.data);
      const def = p.data.find(x => x.typ === 'TENANT_DEFAULT');
      setDefaultSzablon(def ? String(def.szablon_id) : '');
    });
  }, [tenantId]);

  async function saveDefault() {
    if (!defaultSzablon) return;
    setSaving({ default: true });
    try {
      await api.put('/workflow/przypisania', { szablon_id: parseInt(defaultSzablon), typ: 'TENANT_DEFAULT', tenant_id: parseInt(tenantId) });
      setMsg('Domyślny szablon zapisany.');
    } catch (e) { setMsg(e.response?.data?.error || 'Błąd.'); }
    setSaving({});
  }

  async function saveKomorka(komorkaId, szablonId) {
    if (!szablonId) return;
    setSaving({ [komorkaId]: true });
    try {
      await api.put('/workflow/przypisania', { szablon_id: parseInt(szablonId), typ: 'KOMORKA', komorka_id: komorkaId, tenant_id: parseInt(tenantId) });
      const { data } = await api.get(`/workflow/przypisania?tenant_id=${tenantId}`);
      setPrzypisania(data);
      setMsg(`Przypisanie dla komórki zaktualizowane.`);
    } catch (e) { setMsg(e.response?.data?.error || 'Błąd.'); }
    setSaving({});
  }

  const getPrzypisanie = (komorkaId) => {
    const p = przypisania.find(x => x.komorka_id === komorkaId);
    return p ? String(p.szablon_id) : '';
  };

  return (
    <div className="max-w-3xl space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Przypisania szablonów workflow</h1>

      <div className="card p-5 space-y-4">
        <div>
          <label className="form-label">Jednostka</label>
          <select
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:outline-none"
            value={tenantId}
            onChange={e => setTenantId(e.target.value)}
          >
            <option value="">-- Wybierz --</option>
            {tenants.map(t => <option key={t.id} value={t.id}>{t.nazwa}</option>)}
          </select>
        </div>
      </div>

      {tenantId && (
        <>
          {msg && <div className="p-3 bg-green-50 border border-green-200 rounded text-sm text-green-700">{msg}</div>}

          {/* Default */}
          <div className="card p-5 space-y-3">
            <h2 className="font-semibold">Domyślny szablon jednostki</h2>
            <p className="text-xs text-gray-500">Stosowany gdy komórka nie ma własnego przypisania.</p>
            <div className="flex gap-3">
              <select
                className="flex-1 border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:outline-none"
                value={defaultSzablon}
                onChange={e => setDefaultSzablon(e.target.value)}
              >
                <option value="">-- Brak --</option>
                {szablony.map(s => <option key={s.id} value={s.id}>{s.nazwa}</option>)}
              </select>
              <button onClick={saveDefault} disabled={saving.default} className="btn-primary btn-sm">Zapisz</button>
            </div>
          </div>

          {/* Per-komorka */}
          <div className="card">
            <div className="px-5 py-4 border-b">
              <h2 className="font-semibold">Przypisania per komórka</h2>
            </div>
            <div className="divide-y divide-gray-100">
              {komorki.map(k => {
                const current = getPrzypisanie(k.id);
                return (
                  <div key={k.id} className="px-5 py-3 flex items-center gap-4">
                    <div className="flex-1">
                      <p className="text-sm font-medium text-gray-900">{k.nazwa}</p>
                      <p className="text-xs text-gray-400">{k.kod || '—'}</p>
                    </div>
                    {!current && <span className="text-red-400 text-xs">⚠ Brak przypisania</span>}
                    <select
                      className="w-48 border border-gray-300 rounded px-2 py-1.5 text-sm focus:ring-1 focus:ring-primary-500 focus:outline-none"
                      value={current}
                      onChange={e => saveKomorka(k.id, e.target.value)}
                    >
                      <option value="">Domyślny jednostki</option>
                      {szablony.map(s => <option key={s.id} value={s.id}>{s.nazwa}</option>)}
                    </select>
                  </div>
                );
              })}
              {komorki.length === 0 && (
                <div className="px-5 py-8 text-center text-sm text-gray-400">Brak komórek w tej jednostce.</div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
