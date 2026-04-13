import { useState, useEffect } from 'react';
import api from '../../api/axios';

const EMPTY = { nazwa: '', skrot: '', regon: '', nip: '', dni_do_przegladu: 365 };

export default function AdminJednostki() {
  const [data, setData] = useState([]);
  const [modal, setModal] = useState(null); // null | 'new' | {id,...}
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const load = () => api.get('/tenants').then(r => setData(r.data));
  useEffect(() => { load(); }, []);

  function openNew() { setForm(EMPTY); setError(''); setModal('new'); }
  function openEdit(t) {
    setForm({ nazwa: t.nazwa, skrot: t.skrot || '', regon: t.regon || '', nip: t.nip || '', dni_do_przegladu: t.dni_do_przegladu || 365 });
    setError(''); setModal(t);
  }

  async function submit(e) {
    e.preventDefault();
    setSaving(true); setError('');
    try {
      if (modal === 'new') {
        await api.post('/tenants', form);
      } else {
        await api.put(`/tenants/${modal.id}`, form);
      }
      setModal(null); load();
    } catch (e) { setError(e.response?.data?.error || 'Błąd.'); }
    finally { setSaving(false); }
  }

  async function toggle(id, aktywny) {
    await api.put(`/tenants/${id}`, { aktywny: !aktywny });
    load();
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Jednostki organizacyjne (tenants)</h1>
        <button onClick={openNew} className="btn-primary">+ Nowa jednostka</button>
      </div>

      <div className="card overflow-hidden">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          <thead className="bg-gray-50">
            <tr>
              {['Nazwa', 'Skrót', 'REGON', 'NIP', 'Cykl przeglądu (dni)', 'Status', 'Akcje'].map(h => (
                <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-600 uppercase">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {data.map(t => (
              <tr key={t.id} className="hover:bg-gray-50">
                <td className="px-4 py-3 font-medium">{t.nazwa}</td>
                <td className="px-4 py-3 text-gray-500 font-mono">{t.skrot || '—'}</td>
                <td className="px-4 py-3 text-gray-400 text-xs">{t.regon || '—'}</td>
                <td className="px-4 py-3 text-gray-400 text-xs">{t.nip || '—'}</td>
                <td className="px-4 py-3 text-gray-500">{t.dni_do_przegladu || 365}</td>
                <td className="px-4 py-3">
                  {t.aktywny !== false ? <span className="badge-green">Aktywna</span> : <span className="badge-gray">Nieaktywna</span>}
                </td>
                <td className="px-4 py-3 flex gap-3">
                  <button onClick={() => openEdit(t)} className="text-xs text-primary-600 hover:underline">Edytuj</button>
                  <button onClick={() => toggle(t.id, t.aktywny !== false)} className="text-xs text-gray-500 hover:underline">
                    {t.aktywny !== false ? 'Dezaktywuj' : 'Aktywuj'}
                  </button>
                </td>
              </tr>
            ))}
            {data.length === 0 && (
              <tr><td colSpan={7} className="py-8 text-center text-gray-400">Brak jednostek.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {modal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/40" onClick={() => setModal(null)} />
          <div className="relative bg-white rounded-lg shadow-xl p-6 w-full max-w-md space-y-4">
            <h3 className="text-lg font-semibold">{modal === 'new' ? 'Nowa jednostka' : 'Edytuj jednostkę'}</h3>
            {error && <div className="p-2 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div>}
            <form onSubmit={submit} className="space-y-3">
              <div>
                <label className="form-label">Nazwa *</label>
                <input required type="text" className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={form.nazwa} onChange={e => setForm({ ...form, nazwa: e.target.value })} placeholder="np. Urząd Miejski" />
              </div>
              <div>
                <label className="form-label">Skrót *</label>
                <input required type="text" maxLength={20} className="w-full border border-gray-300 rounded px-3 py-2 text-sm font-mono" value={form.skrot} onChange={e => setForm({ ...form, skrot: e.target.value })} placeholder="np. UM, MOPS, CUW" />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="form-label">REGON</label>
                  <input type="text" className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={form.regon} onChange={e => setForm({ ...form, regon: e.target.value })} />
                </div>
                <div>
                  <label className="form-label">NIP</label>
                  <input type="text" className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={form.nip} onChange={e => setForm({ ...form, nip: e.target.value })} />
                </div>
              </div>
              <div>
                <label className="form-label">Cykl przeglądu uprawnień NIS2 (dni)</label>
                <input type="number" min={30} max={730} className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={form.dni_do_przegladu} onChange={e => setForm({ ...form, dni_do_przegladu: Number(e.target.value) })} />
                <p className="text-xs text-gray-400 mt-1">Rekomendowane: 365 dni (corocznie) zgodnie z NIS2</p>
              </div>
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
