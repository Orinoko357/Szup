import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import api from '../../api/axios';

export default function UprawnieniaMat() {
  const [data, setData] = useState([]);
  const [tenants, setTenants] = useState([]);
  const [tenantId, setTenantId] = useState('');
  const [pracownikId, setPracownikId] = useState('');
  const [systemId, setSystemId] = useState('');
  const [systemy, setSystemy] = useState([]);
  const [aktywne, setAktywne] = useState('true');
  const [loading, setLoading] = useState(false);
  const [cofiModal, setCofiModal] = useState(null);
  const [powod, setPowod] = useState('');
  const [msg, setMsg] = useState('');

  useEffect(() => {
    Promise.all([api.get('/tenants'), api.get('/systemy-it')]).then(([t, s]) => {
      setTenants(t.data);
      setSystemy(s.data);
    });
  }, []);

  useEffect(() => {
    setLoading(true);
    const p = new URLSearchParams();
    if (tenantId) p.set('tenant_id', tenantId);
    if (pracownikId) p.set('pracownik_id', pracownikId);
    if (systemId) p.set('system_id', systemId);
    if (aktywne) p.set('aktywne', aktywne);
    api.get(`/uprawnienia?${p}`).then(r => { setData(r.data); setLoading(false); });
  }, [tenantId, pracownikId, systemId, aktywne]);

  async function cofnij() {
    if (!powod.trim()) return;
    try {
      await api.post(`/uprawnienia/${cofiModal}/cofnij`, { powod });
      setCofiModal(null); setPowod('');
      setMsg('Uprawnienie cofnięte.');
      setData(d => d.filter(u => u.id !== cofiModal));
    } catch (e) { setMsg(e.response?.data?.error || 'Błąd.'); }
  }

  const exportData = (fmt) => {
    const p = new URLSearchParams();
    if (tenantId) p.set('tenant_id', tenantId);
    if (aktywne) p.set('aktywne', aktywne);
    p.set('format', fmt);
    window.open(`/api/uprawnienia?${p}`, '_blank');
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Rejestr uprawnień</h1>
        <div className="flex gap-2">
          <button onClick={() => exportData('xlsx')} className="btn-secondary btn-sm">XLSX</button>
          <button onClick={() => exportData('csv')} className="btn-secondary btn-sm">CSV</button>
          <Link to="/uprawnienia/nadaj" className="btn-primary btn-sm">Nadaj bezpośrednio</Link>
        </div>
      </div>

      {msg && <div className="p-3 bg-green-50 border border-green-200 rounded text-sm text-green-700">{msg}</div>}

      <div className="flex flex-wrap gap-3">
        <select className="border border-gray-300 rounded px-3 py-1.5 text-sm" value={tenantId} onChange={e => setTenantId(e.target.value)}>
          <option value="">Wszystkie jednostki</option>
          {tenants.map(t => <option key={t.id} value={t.id}>{t.nazwa}</option>)}
        </select>
        <select className="border border-gray-300 rounded px-3 py-1.5 text-sm" value={systemId} onChange={e => setSystemId(e.target.value)}>
          <option value="">Wszystkie systemy</option>
          {systemy.map(s => <option key={s.id} value={s.id}>{s.nazwa}</option>)}
        </select>
        <select className="border border-gray-300 rounded px-3 py-1.5 text-sm" value={aktywne} onChange={e => setAktywne(e.target.value)}>
          <option value="true">Aktywne</option>
          <option value="false">Cofnięte</option>
          <option value="">Wszystkie</option>
        </select>
      </div>

      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50">
              <tr>
                {['Pracownik', 'Jednostka', 'System', 'Zakres', 'Uprzyw.', 'Data nadania', 'Wniosek', 'Status', 'Akcje'].map(h => (
                  <th key={h} className="px-3 py-3 text-left text-xs font-semibold text-gray-600 uppercase">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {loading ? (
                <tr><td colSpan={9} className="py-8 text-center"><div className="inline-block animate-spin h-6 w-6 border-4 border-primary-500 border-t-transparent rounded-full" /></td></tr>
              ) : data.map(u => (
                <tr key={u.id} className="hover:bg-gray-50">
                  <td className="px-3 py-2 font-medium">{u.pracownik_nazwa}</td>
                  <td className="px-3 py-2 text-gray-500">{u.tenant_nazwa}</td>
                  <td className="px-3 py-2">{u.system_nazwa}</td>
                  <td className="px-3 py-2">{u.zakres_nazwa}</td>
                  <td className="px-3 py-2">{u.uprzywilejowany ? <span className="badge-red text-xs">TAK</span> : '—'}</td>
                  <td className="px-3 py-2 text-gray-500">{u.data_od ? new Date(u.data_od).toLocaleDateString('pl-PL') : '—'}</td>
                  <td className="px-3 py-2 text-xs">{u.numer || (u.nadane_bezposrednio ? 'Bezpośrednie' : '—')}</td>
                  <td className="px-3 py-2">{u.aktywne ? <span className="badge-green">Aktywne</span> : <span className="badge-red">Cofnięte</span>}</td>
                  <td className="px-3 py-2">
                    {u.aktywne && (
                      <button onClick={() => { setCofiModal(u.id); setPowod(''); }} className="text-xs text-red-600 hover:underline">Cofnij</button>
                    )}
                  </td>
                </tr>
              ))}
              {!loading && data.length === 0 && (
                <tr><td colSpan={9} className="py-8 text-center text-gray-400">Brak uprawnień.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Cofnij modal */}
      {cofiModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/40" onClick={() => setCofiModal(null)} />
          <div className="relative bg-white rounded-lg shadow-xl p-6 w-full max-w-md">
            <h3 className="text-lg font-semibold mb-3">Cofnij uprawnienie</h3>
            <label className="form-label">Powód cofnięcia *</label>
            <textarea className="w-full border border-gray-300 rounded px-3 py-2 text-sm" rows={3} value={powod} onChange={e => setPowod(e.target.value)} placeholder="Opisz powód..." />
            <div className="flex gap-3 mt-4">
              <button onClick={cofnij} disabled={!powod.trim()} className="btn-danger">Cofnij uprawnienie</button>
              <button onClick={() => setCofiModal(null)} className="btn-secondary">Anuluj</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
