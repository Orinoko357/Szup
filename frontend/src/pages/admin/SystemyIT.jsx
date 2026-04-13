import { useState, useEffect } from 'react';
import api from '../../api/axios';

const KRYT = ['NISKI', 'SREDNI', 'WYSOKI', 'KRYTYCZNY'];
const KRYT_BADGE = { NISKI: 'badge-green', SREDNI: 'badge-blue', WYSOKI: 'badge-yellow', KRYTYCZNY: 'badge-red' };
const EMPTY_SYS = { nazwa: '', opis: '', poziom_krytycznosci: 'SREDNI', wlasciciel: '', tenant_id: '' };
const EMPTY_MOD = { nazwa: '', opis: '' };
const EMPTY_ZAK = { nazwa: '', opis: '', uprzywilejowany: false, modul_id: '' };

export default function AdminSystemyIT() {
  const [systemy, setSystemy] = useState([]);
  const [tenants, setTenants] = useState([]);
  const [selected, setSelected] = useState(null);
  const [moduly, setModuly] = useState([]);
  const [zakresy, setZakresy] = useState([]);
  const [tab, setTab] = useState('systemy');

  const [sysModal, setSysModal] = useState(null);
  const [modModal, setModModal] = useState(null);
  const [zakModal, setZakModal] = useState(null);

  const [sysForm, setSysForm] = useState(EMPTY_SYS);
  const [modForm, setModForm] = useState(EMPTY_MOD);
  const [zakForm, setZakForm] = useState(EMPTY_ZAK);

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    api.get('/tenants').then(r => setTenants(r.data));
    api.get('/systemy-it').then(r => setSystemy(r.data));
  }, []);

  const loadModuly = (sysId) => api.get(`/systemy-it/${sysId}/moduly`).then(r => setModuly(r.data));
  const loadZakresy = (sysId) => api.get(`/systemy-it/${sysId}/zakresy`).then(r => setZakresy(r.data));

  function selectSystem(sys) {
    setSelected(sys);
    loadModuly(sys.id);
    loadZakresy(sys.id);
    setTab('moduly');
  }

  async function submitSys(e) {
    e.preventDefault(); setSaving(true); setError('');
    try {
      if (sysModal === 'new') await api.post('/systemy-it', sysForm);
      else await api.put(`/systemy-it/${sysModal.id}`, sysForm);
      setSysModal(null);
      api.get('/systemy-it').then(r => setSystemy(r.data));
    } catch (e) { setError(e.response?.data?.error || 'Błąd.'); }
    finally { setSaving(false); }
  }

  async function submitMod(e) {
    e.preventDefault(); setSaving(true); setError('');
    try {
      if (modModal === 'new') await api.post(`/systemy-it/${selected.id}/moduly`, modForm);
      else await api.put(`/systemy-it/moduly/${modModal.id}`, modForm);
      setModModal(null); loadModuly(selected.id);
    } catch (e) { setError(e.response?.data?.error || 'Błąd.'); }
    finally { setSaving(false); }
  }

  async function submitZak(e) {
    e.preventDefault(); setSaving(true); setError('');
    try {
      if (zakModal === 'new') await api.post(`/systemy-it/${selected.id}/zakresy`, zakForm);
      else await api.put(`/systemy-it/zakresy/${zakModal.id}`, zakForm);
      setZakModal(null); loadZakresy(selected.id);
    } catch (e) { setError(e.response?.data?.error || 'Błąd.'); }
    finally { setSaving(false); }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Systemy IT</h1>
        <button onClick={() => { setSysForm(EMPTY_SYS); setError(''); setSysModal('new'); }} className="btn-primary">+ Nowy system</button>
      </div>

      <div className="grid grid-cols-3 gap-4">
        {/* Systems list */}
        <div className="col-span-1 space-y-2">
          <h2 className="text-sm font-semibold text-gray-600 uppercase tracking-wide">Systemy ({systemy.length})</h2>
          {systemy.map(s => (
            <div key={s.id} onClick={() => selectSystem(s)} className={`card p-3 cursor-pointer transition-colors ${selected?.id === s.id ? 'ring-2 ring-primary-400 bg-primary-50' : 'hover:bg-gray-50'}`}>
              <div className="flex items-start justify-between gap-1">
                <div>
                  <div className="font-medium text-sm">{s.nazwa}</div>
                  <div className="text-xs text-gray-400">{s.tenant_nazwa || 'Wspólny'}</div>
                </div>
                <span className={`${KRYT_BADGE[s.poziom_krytycznosci]} text-xs shrink-0`}>{s.poziom_krytycznosci}</span>
              </div>
            </div>
          ))}
          {systemy.length === 0 && <div className="card p-4 text-center text-gray-400 text-sm">Brak systemów.</div>}
        </div>

        {/* Detail panel */}
        <div className="col-span-2">
          {selected ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="font-semibold text-lg">{selected.nazwa}</h2>
                  <p className="text-sm text-gray-500">{selected.opis}</p>
                </div>
                <button onClick={() => { setSysForm({ nazwa: selected.nazwa, opis: selected.opis || '', poziom_krytycznosci: selected.poziom_krytycznosci, wlasciciel: selected.wlasciciel || '', tenant_id: selected.tenant_id || '' }); setError(''); setSysModal(selected); }} className="btn-secondary btn-sm">Edytuj</button>
              </div>

              <div className="flex gap-2 border-b">
                {['moduly', 'zakresy'].map(t => (
                  <button key={t} onClick={() => setTab(t)} className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px ${tab === t ? 'border-primary-500 text-primary-600' : 'border-transparent text-gray-500 hover:text-gray-700'}`}>
                    {t === 'moduly' ? `Moduły (${moduly.length})` : `Zakresy uprawnień (${zakresy.length})`}
                  </button>
                ))}
              </div>

              {tab === 'moduly' && (
                <div className="space-y-2">
                  <div className="flex justify-end">
                    <button onClick={() => { setModForm(EMPTY_MOD); setError(''); setModModal('new'); }} className="btn-primary btn-sm">+ Nowy moduł</button>
                  </div>
                  {moduly.map(m => (
                    <div key={m.id} className="flex items-center justify-between p-3 border border-gray-200 rounded">
                      <div>
                        <div className="font-medium text-sm">{m.nazwa}</div>
                        {m.opis && <div className="text-xs text-gray-400">{m.opis}</div>}
                      </div>
                      <button onClick={() => { setModForm({ nazwa: m.nazwa, opis: m.opis || '' }); setError(''); setModModal(m); }} className="text-xs text-primary-600 hover:underline">Edytuj</button>
                    </div>
                  ))}
                  {moduly.length === 0 && <div className="p-4 text-center text-gray-400 text-sm">Brak modułów.</div>}
                </div>
              )}

              {tab === 'zakresy' && (
                <div className="space-y-2">
                  <div className="flex justify-end">
                    <button onClick={() => { setZakForm({ ...EMPTY_ZAK, modul_id: moduly[0]?.id || '' }); setError(''); setZakModal('new'); }} className="btn-primary btn-sm">+ Nowy zakres</button>
                  </div>
                  {zakresy.map(z => (
                    <div key={z.id} className="flex items-center justify-between p-3 border border-gray-200 rounded">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-sm">{z.nazwa}</span>
                          {z.uprzywilejowany && <span className="badge-red text-xs">UPRZYWILEJOWANY</span>}
                        </div>
                        <div className="text-xs text-gray-400">{z.modul_nazwa || '—'} {z.opis && `· ${z.opis}`}</div>
                      </div>
                      <button onClick={() => { setZakForm({ nazwa: z.nazwa, opis: z.opis || '', uprzywilejowany: z.uprzywilejowany, modul_id: z.modul_id || '' }); setError(''); setZakModal(z); }} className="text-xs text-primary-600 hover:underline">Edytuj</button>
                    </div>
                  ))}
                  {zakresy.length === 0 && <div className="p-4 text-center text-gray-400 text-sm">Brak zakresów.</div>}
                </div>
              )}
            </div>
          ) : (
            <div className="card p-8 text-center text-gray-400">Wybierz system z listy po lewej.</div>
          )}
        </div>
      </div>

      {/* System modal */}
      {sysModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/40" onClick={() => setSysModal(null)} />
          <div className="relative bg-white rounded-lg shadow-xl p-6 w-full max-w-md space-y-4">
            <h3 className="text-lg font-semibold">{sysModal === 'new' ? 'Nowy system IT' : 'Edytuj system'}</h3>
            {error && <div className="p-2 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div>}
            <form onSubmit={submitSys} className="space-y-3">
              <div><label className="form-label">Nazwa *</label><input required type="text" className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={sysForm.nazwa} onChange={e => setSysForm({ ...sysForm, nazwa: e.target.value })} /></div>
              <div><label className="form-label">Opis</label><textarea className="w-full border border-gray-300 rounded px-3 py-2 text-sm" rows={2} value={sysForm.opis} onChange={e => setSysForm({ ...sysForm, opis: e.target.value })} /></div>
              <div><label className="form-label">Właściciel (imię i nazwisko)</label><input type="text" className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={sysForm.wlasciciel} onChange={e => setSysForm({ ...sysForm, wlasciciel: e.target.value })} /></div>
              <div>
                <label className="form-label">Poziom krytyczności</label>
                <select className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={sysForm.poziom_krytycznosci} onChange={e => setSysForm({ ...sysForm, poziom_krytycznosci: e.target.value })}>
                  {KRYT.map(k => <option key={k} value={k}>{k}</option>)}
                </select>
              </div>
              <div>
                <label className="form-label">Jednostka (właściciel systemu)</label>
                <select className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={sysForm.tenant_id} onChange={e => setSysForm({ ...sysForm, tenant_id: e.target.value })}>
                  <option value="">Wspólny (wszystkie jednostki)</option>
                  {tenants.map(t => <option key={t.id} value={t.id}>{t.nazwa}</option>)}
                </select>
              </div>
              <div className="flex gap-3 pt-2">
                <button type="submit" disabled={saving} className="btn-primary">{saving ? 'Zapisywanie...' : 'Zapisz'}</button>
                <button type="button" onClick={() => setSysModal(null)} className="btn-secondary">Anuluj</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Moduł modal */}
      {modModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/40" onClick={() => setModModal(null)} />
          <div className="relative bg-white rounded-lg shadow-xl p-6 w-full max-w-sm space-y-4">
            <h3 className="text-lg font-semibold">{modModal === 'new' ? 'Nowy moduł' : 'Edytuj moduł'}</h3>
            {error && <div className="p-2 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div>}
            <form onSubmit={submitMod} className="space-y-3">
              <div><label className="form-label">Nazwa *</label><input required type="text" className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={modForm.nazwa} onChange={e => setModForm({ ...modForm, nazwa: e.target.value })} /></div>
              <div><label className="form-label">Opis</label><textarea className="w-full border border-gray-300 rounded px-3 py-2 text-sm" rows={2} value={modForm.opis} onChange={e => setModForm({ ...modForm, opis: e.target.value })} /></div>
              <div className="flex gap-3"><button type="submit" disabled={saving} className="btn-primary">{saving ? 'Zapisywanie...' : 'Zapisz'}</button><button type="button" onClick={() => setModModal(null)} className="btn-secondary">Anuluj</button></div>
            </form>
          </div>
        </div>
      )}

      {/* Zakres modal */}
      {zakModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/40" onClick={() => setZakModal(null)} />
          <div className="relative bg-white rounded-lg shadow-xl p-6 w-full max-w-sm space-y-4">
            <h3 className="text-lg font-semibold">{zakModal === 'new' ? 'Nowy zakres uprawnień' : 'Edytuj zakres'}</h3>
            {error && <div className="p-2 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div>}
            <form onSubmit={submitZak} className="space-y-3">
              <div><label className="form-label">Nazwa *</label><input required type="text" className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={zakForm.nazwa} onChange={e => setZakForm({ ...zakForm, nazwa: e.target.value })} /></div>
              <div><label className="form-label">Opis</label><textarea className="w-full border border-gray-300 rounded px-3 py-2 text-sm" rows={2} value={zakForm.opis} onChange={e => setZakForm({ ...zakForm, opis: e.target.value })} /></div>
              <div>
                <label className="form-label">Moduł</label>
                <select className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={zakForm.modul_id} onChange={e => setZakForm({ ...zakForm, modul_id: e.target.value })}>
                  <option value="">— Brak modułu —</option>
                  {moduly.map(m => <option key={m.id} value={m.id}>{m.nazwa}</option>)}
                </select>
              </div>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={zakForm.uprzywilejowany} onChange={e => setZakForm({ ...zakForm, uprzywilejowany: e.target.checked })} className="rounded" />
                <span className="font-medium text-red-700">Konto uprzywilejowane (podwyższony dostęp)</span>
              </label>
              <div className="flex gap-3"><button type="submit" disabled={saving} className="btn-primary">{saving ? 'Zapisywanie...' : 'Zapisz'}</button><button type="button" onClick={() => setZakModal(null)} className="btn-secondary">Anuluj</button></div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
