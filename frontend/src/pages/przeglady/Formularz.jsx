import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import api from '../../api/axios';

export default function PrzegladFormularz() {
  const { id } = useParams();
  const navigate = useNavigate();
  const isNew = !id;
  const [tenants, setTenants] = useState([]);
  const [form, setForm] = useState({ tenant_id: '', typ: 'CYKLICZNY', uwagi: '' });
  const [przeglad, setPrzeglad] = useState(null);
  const [decyzje, setDecyzje] = useState({});
  const [uzas, setUzas] = useState({});
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.get('/tenants').then(r => setTenants(r.data));
    if (!isNew) {
      api.get(`/przeglady/${id}`).then(r => setPrzeglad(r.data));
    }
  }, [id, isNew]);

  async function create(e) {
    e.preventDefault();
    if (!form.tenant_id) { setError('Wybierz jednostkę.'); return; }
    setSaving(true);
    try {
      const { data } = await api.post('/przeglady', form);
      navigate(`/przeglady/${data.id}`);
    } catch (e) { setError(e.response?.data?.error || 'Błąd.'); setSaving(false); }
  }

  async function saveDecyzja(pozId) {
    const dec = decyzje[pozId];
    const uz = uzas[pozId];
    if (!dec || !uz) { alert('Wybierz decyzję i podaj uzasadnienie.'); return; }
    try {
      await api.patch(`/przeglady/pozycje/${pozId}/decyzja`, { decyzja: dec, uzasadnienie: uz });
      const { data } = await api.get(`/przeglady/${id}`);
      setPrzeglad(data);
    } catch (e) { alert(e.response?.data?.error || 'Błąd.'); }
  }

  async function zakoncz() {
    if (!confirm('Zakończyć przegląd?')) return;
    await api.post(`/przeglady/${id}/zakoncz`);
    navigate('/przeglady');
  }

  if (isNew) return (
    <div className="max-w-lg space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Nowy przegląd uprawnień</h1>
      {error && <div className="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div>}
      <form onSubmit={create} className="card p-5 space-y-4">
        <div>
          <label className="form-label">Jednostka *</label>
          <select required className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={form.tenant_id} onChange={e => setForm({ ...form, tenant_id: e.target.value })}>
            <option value="">-- Wybierz --</option>
            {tenants.map(t => <option key={t.id} value={t.id}>{t.nazwa}</option>)}
          </select>
        </div>
        <div>
          <label className="form-label">Typ przeglądu</label>
          <select className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={form.typ} onChange={e => setForm({ ...form, typ: e.target.value })}>
            <option value="CYKLICZNY">Cykliczny (NIS2)</option>
            <option value="DORAZNY">Doraźny</option>
            <option value="ODEJSCIE">Odejście pracownika</option>
          </select>
        </div>
        <div>
          <label className="form-label">Uwagi</label>
          <textarea className="w-full border border-gray-300 rounded px-3 py-2 text-sm" rows={3} value={form.uwagi} onChange={e => setForm({ ...form, uwagi: e.target.value })} />
        </div>
        <div className="flex gap-3">
          <button type="submit" disabled={saving} className="btn-primary">{saving ? 'Tworzenie...' : 'Utwórz przegląd'}</button>
          <button type="button" onClick={() => navigate('/przeglady')} className="btn-secondary">Anuluj</button>
        </div>
      </form>
    </div>
  );

  if (!przeglad) return <div className="flex justify-center py-20"><div className="animate-spin h-8 w-8 border-4 border-primary-500 border-t-transparent rounded-full" /></div>;

  const pending = przeglad.pozycje?.filter(p => !p.decyzja) || [];

  return (
    <div className="max-w-5xl space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Przegląd #{przeglad.id} – {przeglad.tenant_nazwa}</h1>
          <p className="text-sm text-gray-500">{przeglad.typ} · {przeglad.status} · {new Date(przeglad.data_rozpoczecia).toLocaleDateString('pl-PL')}</p>
        </div>
        {przeglad.status === 'W_TOKU' && pending.length === 0 && (
          <button onClick={zakoncz} className="btn-success">Zakończ przegląd</button>
        )}
      </div>

      <div className="card overflow-hidden">
        <div className="px-5 py-4 border-b flex items-center justify-between">
          <h2 className="font-semibold">Pozycje ({przeglad.pozycje?.length})</h2>
          <span className="text-sm text-gray-500">Oczekuje: {pending.length}</span>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-100 text-sm">
            <thead className="bg-gray-50">
              <tr>
                {['Pracownik', 'System', 'Zakres', 'Uprzyw.', 'Decyzja', 'Uzasadnienie', 'Akcja'].map(h => (
                  <th key={h} className="px-3 py-3 text-left text-xs font-semibold text-gray-600 uppercase">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {przeglad.pozycje?.map(p => (
                <tr key={p.id} className={p.decyzja ? 'opacity-60' : ''}>
                  <td className="px-3 py-2 font-medium">{p.pracownik_nazwa}</td>
                  <td className="px-3 py-2 text-gray-500">{p.system_nazwa}</td>
                  <td className="px-3 py-2">{p.zakres_nazwa}</td>
                  <td className="px-3 py-2">{p.uprzywilejowany ? <span className="badge-red text-xs">TAK</span> : '—'}</td>
                  <td className="px-3 py-2">
                    {p.decyzja ? (
                      <span className={p.decyzja === 'POZOSTAW' ? 'badge-green' : p.decyzja === 'COFNIJ' ? 'badge-red' : 'badge-yellow'}>{p.decyzja}</span>
                    ) : (
                      <select
                        className="border border-gray-300 rounded px-2 py-1 text-xs"
                        value={decyzje[p.id] || ''}
                        onChange={e => setDecyzje({ ...decyzje, [p.id]: e.target.value })}
                      >
                        <option value="">-- Wybierz --</option>
                        <option value="POZOSTAW">Pozostaw</option>
                        <option value="COFNIJ">Cofnij</option>
                        <option value="ZMODYFIKUJ">Zmodyfikuj</option>
                      </select>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {p.decyzja ? <span className="text-gray-500 text-xs">{p.uzasadnienie}</span> : (
                      <input type="text" className="border border-gray-300 rounded px-2 py-1 text-xs w-36" placeholder="Uzasadnienie..." value={uzas[p.id] || ''} onChange={e => setUzas({ ...uzas, [p.id]: e.target.value })} />
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {!p.decyzja && przeglad.status === 'W_TOKU' && (
                      <button onClick={() => saveDecyzja(p.id)} className="text-xs text-primary-600 hover:underline">Zapisz</button>
                    )}
                    {p.decyzja && <span className="text-xs text-gray-400">{p.decydent_nazwa}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <button onClick={() => navigate('/przeglady')} className="text-sm text-gray-500 hover:text-gray-700">← Powrót</button>
    </div>
  );
}
