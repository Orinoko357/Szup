import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import api from '../../api/axios';

export default function SzablonyLista() {
  const [szablony, setSzablony] = useState([]);
  const [tenants, setTenants] = useState([]);
  const [tenantFilter, setTenantFilter] = useState('');
  const [loading, setLoading] = useState(true);

  const load = () => {
    const p = tenantFilter ? `?tenant_id=${tenantFilter}` : '';
    Promise.all([
      api.get(`/workflow/szablony${p}`),
      api.get('/tenants'),
    ]).then(([s, t]) => {
      setSzablony(s.data);
      setTenants(t.data);
      setLoading(false);
    });
  };

  useEffect(() => { load(); }, [tenantFilter]);

  async function deleteSzablon(id) {
    if (!confirm('Usunąć szablon?')) return;
    try {
      await api.delete(`/workflow/szablony/${id}`);
      load();
    } catch (e) {
      alert(e.response?.data?.error || 'Błąd usuwania.');
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Szablony workflow</h1>
        <div className="flex gap-3">
          <Link to="/workflow/przypisania" className="btn-secondary">Przypisania komórek</Link>
          <Link to="/workflow/nowy" className="btn-primary">+ Nowy szablon</Link>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <label className="text-sm text-gray-600">Jednostka:</label>
        <select
          className="border border-gray-300 rounded px-3 py-1.5 text-sm focus:ring-2 focus:ring-primary-500 focus:outline-none"
          value={tenantFilter}
          onChange={e => setTenantFilter(e.target.value)}
        >
          <option value="">Wszystkie</option>
          {tenants.map(t => <option key={t.id} value={t.id}>{t.nazwa}</option>)}
        </select>
      </div>

      {loading ? (
        <div className="flex justify-center py-12"><div className="animate-spin h-8 w-8 border-4 border-primary-500 border-t-transparent rounded-full" /></div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {szablony.map(s => (
            <div key={s.id} className="card p-5 space-y-3">
              <div className="flex items-start justify-between">
                <div>
                  <h3 className="font-semibold text-gray-900">{s.nazwa}</h3>
                  <p className="text-xs text-gray-500">{s.tenant_nazwa}</p>
                </div>
                <span className="badge-blue">{s.liczba_poziomow} etap{s.liczba_poziomow !== 1 ? 'y/ów' : ''}</span>
              </div>
              {s.opis && <p className="text-sm text-gray-600">{s.opis}</p>}
              <p className="text-xs text-gray-400">Przypisań: {s.liczba_przypisań}</p>
              <div className="flex gap-2 pt-2 border-t border-gray-100">
                <Link to={`/workflow/${s.id}`} className="btn-secondary btn-sm flex-1 text-center">Edytuj</Link>
                <button onClick={() => deleteSzablon(s.id)} className="btn-danger btn-sm">Usuń</button>
              </div>
            </div>
          ))}
          {szablony.length === 0 && (
            <div className="col-span-3 card p-12 text-center text-gray-400">
              Brak szablonów. <Link to="/workflow/nowy" className="text-primary-600 hover:underline">Utwórz pierwszy szablon</Link>.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
