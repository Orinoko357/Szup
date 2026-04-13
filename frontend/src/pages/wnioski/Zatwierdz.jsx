import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import api from '../../api/axios';
import { useAuth } from '../../hooks/useAuth';
import WorkflowVisualizer from '../../components/WorkflowVisualizer';

export default function WnioskiZatwierdz() {
  const { id } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [wniosek, setWniosek] = useState(null);
  const [action, setAction] = useState('');
  const [komentarz, setKomentarz] = useState('');
  const [uwagi, setUwagi] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    api.get(`/wnioski/${id}`).then(r => setWniosek(r.data));
  }, [id]);

  const isIT = ['IT_ADMIN', 'SUPERADMIN'].includes(user?.rola);

  // Find current stage for this user
  const currentEtap = wniosek?.etapy?.find(e =>
    e.status === 'OCZEKUJE' && e.zatwierdzajacy_id === user?.pracownik_id
  );

  async function submit() {
    if (!wniosek) return;
    setError('');
    setLoading(true);
    try {
      if (wniosek.status === 'OCZEKUJE_IT') {
        // IT realization
        if (action === 'zrealizuj') {
          await api.post(`/wnioski/${id}/zrealizuj`, { uwagi });
        } else if (action === 'odrzuc') {
          if (!komentarz) { setError('Podaj powód odrzucenia.'); setLoading(false); return; }
          await api.post(`/wnioski/${id}/it-odrzuc`, { powod: komentarz });
        }
      } else if (currentEtap) {
        const etapKolejnosc = currentEtap.kolejnosc;
        if (action === 'zatwierdz') {
          await api.post(`/wnioski/${id}/zatwierdz`, { etap_kolejnosc: etapKolejnosc, komentarz });
        } else if (action === 'odrzuc') {
          if (!komentarz) { setError('Podaj powód odrzucenia.'); setLoading(false); return; }
          await api.post(`/wnioski/${id}/odrzuc`, { etap_kolejnosc: etapKolejnosc, powod: komentarz });
        } else if (action === 'odeslij') {
          if (!komentarz) { setError('Podaj komentarz.'); setLoading(false); return; }
          await api.post(`/wnioski/${id}/odeslij`, { etap_kolejnosc: etapKolejnosc, komentarz });
        } else if (action === 'pomin') {
          if (!komentarz) { setError('Podaj powód pominięcia.'); setLoading(false); return; }
          await api.post(`/wnioski/${id}/pomin`, { etap_kolejnosc: etapKolejnosc, powod: komentarz });
        }
      }
      navigate(`/wnioski/${id}`);
    } catch (e) {
      setError(e.response?.data?.error || 'Błąd operacji.');
    } finally {
      setLoading(false);
    }
  }

  if (!wniosek) return <div className="flex justify-center py-20"><div className="animate-spin h-8 w-8 border-4 border-primary-500 border-t-transparent rounded-full" /></div>;

  const isITRealization = isIT && wniosek.status === 'OCZEKUJE_IT';
  const isApprovalStage = !!currentEtap;

  return (
    <div className="max-w-3xl space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">
        {isITRealization ? 'Realizacja wniosku' : 'Zatwierdzanie'}: {wniosek.numer}
      </h1>

      {/* Workflow path */}
      {wniosek.etapy?.length > 0 && (
        <div className="card p-4">
          <WorkflowVisualizer etapy={wniosek.etapy} aktualnyEtap={wniosek.aktualny_etap_kolejnosc} />
        </div>
      )}

      {/* Employee + positions */}
      <div className="card p-5 space-y-3">
        <h3 className="font-semibold">Pracownik: {wniosek.pracownik_nazwa}</h3>
        <p className="text-sm text-gray-500">{wniosek.stanowisko} · {wniosek.komorka_nazwa} · {wniosek.tenant_nazwa}</p>
        <div className="overflow-x-auto mt-2">
          <table className="min-w-full text-sm divide-y divide-gray-100">
            <thead className="bg-gray-50">
              <tr>
                {['System', 'Moduł', 'Zakres', 'Uprzyw.', 'Uzasadnienie'].map(h => (
                  <th key={h} className="px-3 py-2 text-left text-xs font-semibold text-gray-600 uppercase">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {wniosek.pozycje?.map(p => (
                <tr key={p.id}>
                  <td className="px-3 py-2 font-medium">{p.system_nazwa}</td>
                  <td className="px-3 py-2 text-gray-500">{p.modul_nazwa || '—'}</td>
                  <td className="px-3 py-2">{p.zakres_nazwa}</td>
                  <td className="px-3 py-2">{p.uprzywilejowany ? <span className="badge-red text-xs">TAK</span> : '—'}</td>
                  <td className="px-3 py-2 text-gray-500">{p.uzasadnienie || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {error && <div className="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div>}

      {/* Actions */}
      {(isITRealization || isApprovalStage) && (
        <div className="card p-5 space-y-4">
          <h3 className="font-semibold">Podjij decyzję</h3>

          <div className="flex flex-wrap gap-2">
            {isITRealization ? (
              <>
                <button onClick={() => setAction('zrealizuj')} className={`btn ${action === 'zrealizuj' ? 'btn-success' : 'btn-secondary'}`}>Zrealizuj</button>
                <button onClick={() => setAction('odrzuc')} className={`btn ${action === 'odrzuc' ? 'btn-danger' : 'btn-secondary'}`}>Odrzuć</button>
              </>
            ) : (
              <>
                <button onClick={() => setAction('zatwierdz')} className={`btn ${action === 'zatwierdz' ? 'btn-success' : 'btn-secondary'}`}>Zatwierdź</button>
                <button onClick={() => setAction('odrzuc')} className={`btn ${action === 'odrzuc' ? 'btn-danger' : 'btn-secondary'}`}>Odrzuć</button>
                <button onClick={() => setAction('odeslij')} className={`btn ${action === 'odeslij' ? 'btn-warning' : 'btn-secondary'}`}>Odeślij do poprawy</button>
                {currentEtap?.opcjonalny && (
                  <button onClick={() => setAction('pomin')} className={`btn ${action === 'pomin' ? 'badge-gray' : 'btn-secondary'}`}>Pomiń etap</button>
                )}
              </>
            )}
          </div>

          {action && (
            <div>
              {action === 'zrealizuj' ? (
                <div>
                  <label className="form-label">Uwagi IT (opcjonalne)</label>
                  <textarea className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:outline-none" rows={3} value={uwagi} onChange={e => setUwagi(e.target.value)} />
                </div>
              ) : (
                <div>
                  <label className="form-label">
                    {action === 'odrzuc' ? 'Powód odrzucenia *' :
                     action === 'odeslij' ? 'Komentarz do poprawy *' :
                     action === 'pomin' ? 'Powód pominięcia *' : 'Komentarz'}
                  </label>
                  <textarea
                    className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:outline-none"
                    rows={3}
                    value={komentarz}
                    onChange={e => setKomentarz(e.target.value)}
                    placeholder="Opisz powód..."
                  />
                </div>
              )}
              <div className="flex gap-3 mt-4">
                <button onClick={submit} disabled={loading} className={`btn ${action === 'zatwierdz' || action === 'zrealizuj' ? 'btn-success' : action === 'odrzuc' ? 'btn-danger' : 'btn-warning'}`}>
                  {loading ? 'Zapisywanie...' : 'Potwierdź'}
                </button>
                <button onClick={() => setAction('')} className="btn-secondary">Anuluj</button>
              </div>
            </div>
          )}
        </div>
      )}

      {!isITRealization && !isApprovalStage && (
        <div className="card p-5 text-center text-gray-400">
          Nie jesteś zatwierdzającym dla aktualnego etapu tego wniosku.
        </div>
      )}

      <button onClick={() => navigate(`/wnioski/${id}`)} className="text-sm text-gray-500 hover:text-gray-700">
        ← Powrót do wniosku
      </button>
    </div>
  );
}
