import { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import api from '../../api/axios';
import { useAuth } from '../../hooks/useAuth';
import WorkflowVisualizer from '../../components/WorkflowVisualizer';

export default function WnioskiNowy() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [sp] = useSearchParams();
  const pracownikIdInit = sp.get('pracownik_id');

  const [pracownicy, setPracownicy] = useState([]);
  const [systemy, setSystemy] = useState([]);
  const [pracownikId, setPracownikId] = useState(pracownikIdInit || '');
  const [workflow, setWorkflow] = useState(null);
  const [pozycje, setPozycje] = useState([{ system_id: '', modul_id: '', zakres_id: '', uzasadnienie: '' }]);
  const [uwagi, setUwagi] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api.get('/pracownicy?aktywny=true').then(r => setPracownicy(r.data));
    api.get('/systemy-it').then(r => setSystemy(r.data));
  }, []);

  useEffect(() => {
    if (!pracownikId) { setWorkflow(null); return; }
    api.get(`/workflow/resolve/${pracownikId}`)
      .then(r => setWorkflow(r.data))
      .catch(e => setWorkflow({ error: e.response?.data?.error || 'Błąd' }));
  }, [pracownikId]);

  const addPozycja = () => setPozycje([...pozycje, { system_id: '', modul_id: '', zakres_id: '', uzasadnienie: '' }]);
  const removePozycja = i => setPozycje(pozycje.filter((_, idx) => idx !== i));
  const updatePozycja = (i, field, val) => {
    const updated = [...pozycje];
    updated[i] = { ...updated[i], [field]: val };
    if (field === 'system_id') { updated[i].modul_id = ''; updated[i].zakres_id = ''; }
    if (field === 'modul_id') updated[i].zakres_id = '';
    setPozycje(updated);
  };

  const getModuly = (systemId) => {
    const sys = systemy.find(s => s.id === parseInt(systemId));
    return sys?.moduly || [];
  };
  const getZakresy = (systemId, modulId) => {
    const sys = systemy.find(s => s.id === parseInt(systemId));
    if (!sys) return [];
    return (sys.zakresy || []).filter(z => !modulId || z.modul_id === parseInt(modulId) || !z.modul_id);
  };

  async function handleSubmit(zloz) {
    setError('');
    if (!pracownikId) { setError('Wybierz pracownika.'); return; }
    if (pozycje.some(p => !p.system_id || !p.zakres_id)) {
      setError('Uzupełnij wszystkie pozycje (system i zakres są wymagane).');
      return;
    }
    setLoading(true);
    try {
      const { data } = await api.post('/wnioski', {
        pracownik_id: parseInt(pracownikId),
        pozycje: pozycje.map(p => ({
          system_id: parseInt(p.system_id),
          modul_id: p.modul_id ? parseInt(p.modul_id) : null,
          zakres_id: parseInt(p.zakres_id),
          uzasadnienie: p.uzasadnienie,
        })),
        uwagi_inicjujacego: uwagi,
        zloz,
      });
      navigate(`/wnioski/${data.id}`);
    } catch (e) {
      setError(e.response?.data?.error || 'Błąd zapisu.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="max-w-3xl space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Nowy wniosek o uprawnienia</h1>

      {error && <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">{error}</div>}

      {/* Pracownik */}
      <div className="card p-5 space-y-4">
        <h2 className="font-semibold text-gray-900">Pracownik</h2>
        <div>
          <label className="form-label">Wybierz pracownika</label>
          <select
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:outline-none"
            value={pracownikId}
            onChange={e => setPracownikId(e.target.value)}
          >
            <option value="">-- Wybierz --</option>
            {pracownicy.map(p => (
              <option key={p.id} value={p.id}>
                {p.imie} {p.nazwisko} · {p.stanowisko || '—'} · {p.tenant_nazwa}
              </option>
            ))}
          </select>
        </div>

        {workflow && !workflow.error && (
          <div>
            <p className="text-xs font-medium text-gray-500 mb-2">Ścieżka zatwierdzania:</p>
            <WorkflowVisualizer etapy={workflow.poziomy} />
          </div>
        )}
        {workflow?.error && (
          <div className="p-3 bg-yellow-50 border border-yellow-200 rounded text-sm text-yellow-700">
            ⚠ {workflow.error}
          </div>
        )}
      </div>

      {/* Pozycje */}
      <div className="card p-5 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold text-gray-900">Wnioskowane uprawnienia</h2>
          <button onClick={addPozycja} className="btn-secondary btn-sm">+ Dodaj pozycję</button>
        </div>

        {pozycje.map((poz, i) => {
          const moduly = getModuly(poz.system_id);
          const zakresy = getZakresy(poz.system_id, poz.modul_id);
          return (
            <div key={i} className="border border-gray-200 rounded-lg p-4 space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-gray-600">Pozycja {i + 1}</span>
                {pozycje.length > 1 && (
                  <button onClick={() => removePozycja(i)} className="text-red-500 hover:text-red-700 text-xs">Usuń</button>
                )}
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="form-label">System *</label>
                  <select
                    className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:ring-1 focus:ring-primary-500 focus:outline-none"
                    value={poz.system_id}
                    onChange={e => updatePozycja(i, 'system_id', e.target.value)}
                  >
                    <option value="">-- Wybierz --</option>
                    {systemy.map(s => <option key={s.id} value={s.id}>{s.nazwa}</option>)}
                  </select>
                </div>
                <div>
                  <label className="form-label">Moduł</label>
                  <select
                    className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:ring-1 focus:ring-primary-500 focus:outline-none"
                    value={poz.modul_id}
                    onChange={e => updatePozycja(i, 'modul_id', e.target.value)}
                    disabled={!poz.system_id || moduly.length === 0}
                  >
                    <option value="">Brak / Wszystkie</option>
                    {moduly.map(m => <option key={m.id} value={m.id}>{m.nazwa}</option>)}
                  </select>
                </div>
                <div>
                  <label className="form-label">Zakres *</label>
                  <select
                    className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:ring-1 focus:ring-primary-500 focus:outline-none"
                    value={poz.zakres_id}
                    onChange={e => updatePozycja(i, 'zakres_id', e.target.value)}
                    disabled={!poz.system_id}
                  >
                    <option value="">-- Wybierz --</option>
                    {zakresy.map(z => (
                      <option key={z.id} value={z.id}>
                        {z.nazwa}{z.uprzywilejowany ? ' ⚠ [UPRZYWILEJOWANY]' : ''}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="form-label">Uzasadnienie</label>
                  <input
                    type="text"
                    className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:ring-1 focus:ring-primary-500 focus:outline-none"
                    value={poz.uzasadnienie}
                    onChange={e => updatePozycja(i, 'uzasadnienie', e.target.value)}
                    placeholder="Powód nadania uprawnienia..."
                  />
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Uwagi */}
      <div className="card p-5">
        <label className="form-label">Uwagi inicjującego</label>
        <textarea
          className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:outline-none"
          rows={3}
          value={uwagi}
          onChange={e => setUwagi(e.target.value)}
          placeholder="Opcjonalne uwagi..."
        />
      </div>

      <div className="flex gap-3">
        <button onClick={() => handleSubmit(false)} disabled={loading} className="btn-secondary">
          Zapisz jako szkic
        </button>
        <button onClick={() => handleSubmit(true)} disabled={loading || !!workflow?.error} className="btn-primary">
          {loading ? 'Wysyłanie...' : 'Złóż wniosek'}
        </button>
        <button onClick={() => navigate(-1)} className="btn-secondary ml-auto">Anuluj</button>
      </div>
    </div>
  );
}
