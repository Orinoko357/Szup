import { useState, useEffect } from 'react';
import api from '../../api/axios';

export default function AdminStrukturaOrg() {
  const [tenants, setTenants] = useState([]);
  const [tenantId, setTenantId] = useState('');
  const [struktura, setStruktura] = useState([]);
  const [komorki, setKomorki] = useState([]);
  const [modal, setModal] = useState(null);
  const [form, setForm] = useState({ nazwa: '', nadrzedny_id: '', tenant_id: '' });
  const [komorkaForm, setKomorkaForm] = useState({ nazwa: '', kod: '', struktura_org_id: '', tenant_id: '' });
  const [komorkaModal, setKomorkaModal] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [tab, setTab] = useState('struktura');

  useEffect(() => { api.get('/tenants').then(r => setTenants(r.data)); }, []);

  const loadStruktura = () => {
    if (!tenantId) return;
    api.get(`/struktura-org?tenant_id=${tenantId}`).then(r => setStruktura(r.data));
  };
  const loadKomorki = () => {
    if (!tenantId) return;
    api.get(`/komorki?tenant_id=${tenantId}`).then(r => setKomorki(r.data));
  };

  useEffect(() => {
    if (!tenantId) { setStruktura([]); setKomorki([]); return; }
    loadStruktura();
    loadKomorki();
  }, [tenantId]);

  function buildTree(nodes, parentId = null) {
    return nodes.filter(n => (n.nadrzedny_id || null) === parentId).map(n => ({
      ...n, children: buildTree(nodes, n.id),
    }));
  }

  function renderNode(node, depth = 0) {
    return (
      <div key={node.id}>
        <div className={`flex items-center gap-2 py-1.5 px-3 hover:bg-gray-50 rounded`} style={{ paddingLeft: `${depth * 20 + 12}px` }}>
          <span className="text-gray-400">{'└─'.slice(depth === 0 ? 2 : 0)}</span>
          <span className="font-medium text-sm">{node.nazwa}</span>
          {node.kod && <span className="text-xs text-gray-400 font-mono">[{node.kod}]</span>}
          <div className="ml-auto flex gap-2">
            <button onClick={() => { setForm({ nazwa: '', nadrzedny_id: node.id, tenant_id: tenantId }); setError(''); setModal('new'); }} className="text-xs text-primary-600 hover:underline">+ Podjednostka</button>
            <button onClick={() => { setForm({ nazwa: node.nazwa, nadrzedny_id: node.nadrzedny_id || '', tenant_id: tenantId }); setError(''); setModal(node); }} className="text-xs text-gray-500 hover:underline">Edytuj</button>
          </div>
        </div>
        {node.children?.map(c => renderNode(c, depth + 1))}
      </div>
    );
  }

  async function submitStruktura(e) {
    e.preventDefault();
    setSaving(true); setError('');
    try {
      if (modal === 'new') {
        await api.post('/struktura-org', { ...form, tenant_id: tenantId });
      } else {
        await api.put(`/struktura-org/${modal.id}`, form);
      }
      setModal(null); loadStruktura();
    } catch (e) { setError(e.response?.data?.error || 'Błąd.'); }
    finally { setSaving(false); }
  }

  async function submitKomorka(e) {
    e.preventDefault();
    setSaving(true); setError('');
    try {
      if (komorkaModal === 'new') {
        await api.post('/komorki', { ...komorkaForm, tenant_id: tenantId });
      } else {
        await api.put(`/komorki/${komorkaModal.id}`, komorkaForm);
      }
      setKomorkaModal(null); loadKomorki();
    } catch (e) { setError(e.response?.data?.error || 'Błąd.'); }
    finally { setSaving(false); }
  }

  const tree = buildTree(struktura);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Struktura organizacyjna</h1>
      </div>

      <select className="border border-gray-300 rounded px-3 py-1.5 text-sm" value={tenantId} onChange={e => setTenantId(e.target.value)}>
        <option value="">-- Wybierz jednostkę --</option>
        {tenants.map(t => <option key={t.id} value={t.id}>{t.nazwa}</option>)}
      </select>

      {tenantId && (
        <>
          <div className="flex gap-2 border-b">
            {['struktura', 'komorki'].map(t => (
              <button key={t} onClick={() => setTab(t)} className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${tab === t ? 'border-primary-500 text-primary-600' : 'border-transparent text-gray-500 hover:text-gray-700'}`}>
                {t === 'struktura' ? 'Struktura org. (wydziały)' : 'Komórki organizacyjne'}
              </button>
            ))}
          </div>

          {tab === 'struktura' && (
            <div className="space-y-3">
              <div className="flex justify-end">
                <button onClick={() => { setForm({ nazwa: '', nadrzedny_id: '', tenant_id: tenantId }); setError(''); setModal('new'); }} className="btn-primary btn-sm">+ Dodaj węzeł główny</button>
              </div>
              <div className="card p-2">
                {tree.length === 0 ? (
                  <div className="p-8 text-center text-gray-400">Brak struktury. Dodaj pierwszy węzeł.</div>
                ) : tree.map(n => renderNode(n))}
              </div>
            </div>
          )}

          {tab === 'komorki' && (
            <div className="space-y-3">
              <div className="flex justify-end">
                <button onClick={() => { setKomorkaForm({ nazwa: '', kod: '', struktura_org_id: '', tenant_id: tenantId }); setError(''); setKomorkaModal('new'); }} className="btn-primary btn-sm">+ Nowa komórka</button>
              </div>
              <div className="card overflow-hidden">
                <table className="min-w-full divide-y divide-gray-200 text-sm">
                  <thead className="bg-gray-50">
                    <tr>{['Nazwa', 'Kod', 'Jednostka organizacyjna', 'Akcje'].map(h => <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-600 uppercase">{h}</th>)}</tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {komorki.map(k => (
                      <tr key={k.id} className="hover:bg-gray-50">
                        <td className="px-4 py-3 font-medium">{k.nazwa}</td>
                        <td className="px-4 py-3 text-gray-400 font-mono text-xs">{k.kod || '—'}</td>
                        <td className="px-4 py-3 text-gray-500">{k.struktura_nazwa || '—'}</td>
                        <td className="px-4 py-3">
                          <button onClick={() => { setKomorkaForm({ nazwa: k.nazwa, kod: k.kod || '', struktura_org_id: k.struktura_org_id || '', tenant_id: tenantId }); setError(''); setKomorkaModal(k); }} className="text-xs text-primary-600 hover:underline">Edytuj</button>
                        </td>
                      </tr>
                    ))}
                    {komorki.length === 0 && <tr><td colSpan={4} className="py-8 text-center text-gray-400">Brak komórek.</td></tr>}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}

      {/* Struktura modal */}
      {modal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/40" onClick={() => setModal(null)} />
          <div className="relative bg-white rounded-lg shadow-xl p-6 w-full max-w-md space-y-4">
            <h3 className="text-lg font-semibold">{modal === 'new' ? 'Nowy węzeł struktury' : 'Edytuj węzeł'}</h3>
            {error && <div className="p-2 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div>}
            <form onSubmit={submitStruktura} className="space-y-3">
              <div>
                <label className="form-label">Nazwa *</label>
                <input required type="text" className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={form.nazwa} onChange={e => setForm({ ...form, nazwa: e.target.value })} />
              </div>
              {modal === 'new' && (
                <div>
                  <label className="form-label">Nadrzędna jednostka</label>
                  <select className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={form.nadrzedny_id} onChange={e => setForm({ ...form, nadrzedny_id: e.target.value })}>
                    <option value="">— Brak (węzeł główny) —</option>
                    {struktura.map(s => <option key={s.id} value={s.id}>{s.nazwa}</option>)}
                  </select>
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

      {/* Komórka modal */}
      {komorkaModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/40" onClick={() => setKomorkaModal(null)} />
          <div className="relative bg-white rounded-lg shadow-xl p-6 w-full max-w-md space-y-4">
            <h3 className="text-lg font-semibold">{komorkaModal === 'new' ? 'Nowa komórka' : 'Edytuj komórkę'}</h3>
            {error && <div className="p-2 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div>}
            <form onSubmit={submitKomorka} className="space-y-3">
              <div>
                <label className="form-label">Nazwa *</label>
                <input required type="text" className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={komorkaForm.nazwa} onChange={e => setKomorkaForm({ ...komorkaForm, nazwa: e.target.value })} />
              </div>
              <div>
                <label className="form-label">Kod</label>
                <input type="text" className="w-full border border-gray-300 rounded px-3 py-2 text-sm font-mono" value={komorkaForm.kod} onChange={e => setKomorkaForm({ ...komorkaForm, kod: e.target.value })} />
              </div>
              <div>
                <label className="form-label">Jednostka organizacyjna</label>
                <select className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={komorkaForm.struktura_org_id} onChange={e => setKomorkaForm({ ...komorkaForm, struktura_org_id: e.target.value })}>
                  <option value="">— Brak —</option>
                  {struktura.map(s => <option key={s.id} value={s.id}>{s.nazwa}</option>)}
                </select>
              </div>
              <div className="flex gap-3 pt-2">
                <button type="submit" disabled={saving} className="btn-primary">{saving ? 'Zapisywanie...' : 'Zapisz'}</button>
                <button type="button" onClick={() => setKomorkaModal(null)} className="btn-secondary">Anuluj</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
