import { useState, useEffect } from 'react';
import api from '../../api/axios';

const TYP_BADGE = { BEZPIECZENSTWO: 'badge-red', AWARIA: 'badge-yellow', INCYDENT_NIS2: 'badge-purple', INNY: 'badge-gray' };
const POZIOM_BADGE = { NISKI: 'badge-green', SREDNI: 'badge-blue', WYSOKI: 'badge-yellow', KRYTYCZNY: 'badge-red' };
const STATUS_BADGE = { NOWY: 'badge-blue', W_TRAKCIE: 'badge-yellow', ZAMKNIETY: 'badge-green', ESKALOWANY: 'badge-red' };

const EMPTY = { tenant_id: '', typ: 'BEZPIECZENSTWO', poziom: 'SREDNI', tytul: '', opis: '', data_wystapienia: new Date().toISOString().split('T')[0] };

export default function RejestrIncydenty() {
  const [data, setData] = useState([]);
  const [tenants, setTenants] = useState([]);
  const [tenantId, setTenantId] = useState('');
  const [loading, setLoading] = useState(false);
  const [modal, setModal] = useState(false);
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => { api.get('/tenants').then(r => setTenants(r.data)); }, []);

  const load = () => {
    setLoading(true);
    const p = tenantId ? `?tenant_id=${tenantId}` : '';
    api.get(`/incydenty${p}`).then(r => { setData(r.data); setLoading(false); });
  };

  useEffect(() => { load(); }, [tenantId]);

  async function submit(e) {
    e.preventDefault();
    setSaving(true); setError('');
    try {
      await api.post('/incydenty', form);
      setModal(false); setForm(EMPTY);
      load();
    } catch (e) { setError(e.response?.data?.error || 'Błąd zapisu.'); }
    finally { setSaving(false); }
  }

  async function updateStatus(id, status) {
    await api.patch(`/incydenty/${id}`, { status });
    load();
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Rejestr incydentów</h1>
        <button onClick={() => setModal(true)} className="btn-primary">+ Nowy incydent</button>
      </div>

      <select className="border border-gray-300 rounded px-3 py-1.5 text-sm" value={tenantId} onChange={e => setTenantId(e.target.value)}>
        <option value="">Wszystkie jednostki</option>
        {tenants.map(t => <option key={t.id} value={t.id}>{t.nazwa}</option>)}
      </select>

      <div className="card overflow-hidden">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          <thead className="bg-gray-50">
            <tr>
              {['Nr', 'Tytuł', 'Jednostka', 'Typ', 'Poziom', 'Status', 'Data wystąp.', 'Zgłaszający', 'Akcje'].map(h => (
                <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-600 uppercase">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {loading ? (
              <tr><td colSpan={9} className="py-8 text-center"><div className="inline-block animate-spin h-6 w-6 border-4 border-primary-500 border-t-transparent rounded-full" /></td></tr>
            ) : data.map(inc => (
              <tr key={inc.id} className="hover:bg-gray-50">
                <td className="px-4 py-3 font-medium text-gray-400">#{inc.id}</td>
                <td className="px-4 py-3 font-medium max-w-xs truncate">{inc.tytul}</td>
                <td className="px-4 py-3 text-gray-500">{inc.tenant_nazwa}</td>
                <td className="px-4 py-3"><span className={TYP_BADGE[inc.typ] || 'badge-gray'}>{inc.typ.replace('_', ' ')}</span></td>
                <td className="px-4 py-3"><span className={POZIOM_BADGE[inc.poziom] || 'badge-gray'}>{inc.poziom}</span></td>
                <td className="px-4 py-3"><span className={STATUS_BADGE[inc.status] || 'badge-gray'}>{inc.status}</span></td>
                <td className="px-4 py-3 text-gray-500">{new Date(inc.data_wystapienia).toLocaleDateString('pl-PL')}</td>
                <td className="px-4 py-3 text-gray-500">{inc.zglaszajacy_nazwa}</td>
                <td className="px-4 py-3">
                  {inc.status === 'NOWY' && (
                    <button onClick={() => updateStatus(inc.id, 'W_TRAKCIE')} className="text-xs text-blue-600 hover:underline mr-2">Przejmij</button>
                  )}
                  {inc.status !== 'ZAMKNIETY' && (
                    <button onClick={() => updateStatus(inc.id, 'ZAMKNIETY')} className="text-xs text-green-600 hover:underline">Zamknij</button>
                  )}
                </td>
              </tr>
            ))}
            {!loading && data.length === 0 && (
              <tr><td colSpan={9} className="py-8 text-center text-gray-400">Brak incydentów.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {modal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/40" onClick={() => setModal(false)} />
          <div className="relative bg-white rounded-lg shadow-xl p-6 w-full max-w-lg space-y-4">
            <h3 className="text-lg font-semibold">Nowy incydent</h3>
            {error && <div className="p-2 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div>}
            <form onSubmit={submit} className="space-y-3">
              <div>
                <label className="form-label">Jednostka *</label>
                <select required className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={form.tenant_id} onChange={e => setForm({ ...form, tenant_id: e.target.value })}>
                  <option value="">-- Wybierz --</option>
                  {tenants.map(t => <option key={t.id} value={t.id}>{t.nazwa}</option>)}
                </select>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="form-label">Typ</label>
                  <select className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={form.typ} onChange={e => setForm({ ...form, typ: e.target.value })}>
                    <option value="BEZPIECZENSTWO">Bezpieczeństwo</option>
                    <option value="AWARIA">Awaria</option>
                    <option value="INCYDENT_NIS2">Incydent NIS2</option>
                    <option value="INNY">Inny</option>
                  </select>
                </div>
                <div>
                  <label className="form-label">Poziom</label>
                  <select className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={form.poziom} onChange={e => setForm({ ...form, poziom: e.target.value })}>
                    <option value="NISKI">Niski</option>
                    <option value="SREDNI">Średni</option>
                    <option value="WYSOKI">Wysoki</option>
                    <option value="KRYTYCZNY">Krytyczny</option>
                  </select>
                </div>
              </div>
              <div>
                <label className="form-label">Tytuł *</label>
                <input required type="text" className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={form.tytul} onChange={e => setForm({ ...form, tytul: e.target.value })} />
              </div>
              <div>
                <label className="form-label">Opis</label>
                <textarea className="w-full border border-gray-300 rounded px-3 py-2 text-sm" rows={3} value={form.opis} onChange={e => setForm({ ...form, opis: e.target.value })} />
              </div>
              <div>
                <label className="form-label">Data wystąpienia</label>
                <input type="date" className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={form.data_wystapienia} onChange={e => setForm({ ...form, data_wystapienia: e.target.value })} />
              </div>
              <div className="flex gap-3 pt-2">
                <button type="submit" disabled={saving} className="btn-primary">{saving ? 'Zapisywanie...' : 'Zgłoś incydent'}</button>
                <button type="button" onClick={() => setModal(false)} className="btn-secondary">Anuluj</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
