import { useState, useEffect } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import api from '../../api/axios';
import { useAuth } from '../../hooks/useAuth';
import WorkflowVisualizer from '../../components/WorkflowVisualizer';

const STATUS_BADGE = { SZKIC:'badge-gray',W_TOKU:'badge-blue',WYMAGA_POPRAWY:'badge-yellow',OCZEKUJE_IT:'badge-purple',ZREALIZOWANY:'badge-green',ODRZUCONY:'badge-red' };
const STATUS_LABEL = { SZKIC:'Szkic',W_TOKU:'W toku',WYMAGA_POPRAWY:'Wymaga poprawy',OCZEKUJE_IT:'Oczekuje IT',ZREALIZOWANY:'Zrealizowany',ODRZUCONY:'Odrzucony' };

export default function WnioskiSzczegoly() {
  const { id } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [wniosek, setWniosek] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    api.get(`/wnioski/${id}`).then(r => { setWniosek(r.data); setLoading(false); });
  };

  useEffect(load, [id]);

  const isIT = ['IT_ADMIN', 'SUPERADMIN'].includes(user?.rola);

  // Check if current user is an approver for current stage
  const isApprover = wniosek && user?.pracownik_id &&
    wniosek.etapy?.some(e => e.status === 'OCZEKUJE' && e.zatwierdzajacy_id === user.pracownik_id);

  if (loading) return <div className="flex justify-center py-20"><div className="animate-spin h-8 w-8 border-4 border-primary-500 border-t-transparent rounded-full" /></div>;
  if (!wniosek) return <div className="text-center py-20 text-gray-400">Nie znaleziono wniosku.</div>;

  return (
    <div className="max-w-4xl space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-gray-900">{wniosek.numer || '(szkic)'}</h1>
            <span className={STATUS_BADGE[wniosek.status]}>{STATUS_LABEL[wniosek.status]}</span>
          </div>
          <p className="text-sm text-gray-500 mt-1">
            {wniosek.tenant_nazwa} · Inicjowany: {new Date(wniosek.data_utworzenia).toLocaleDateString('pl-PL')}
          </p>
        </div>
        <div className="flex gap-2">
          {isIT && wniosek.status === 'OCZEKUJE_IT' && (
            <Link to={`/wnioski/${id}/zatwierdz`} className="btn-primary">Realizuj</Link>
          )}
          {isApprover && (
            <Link to={`/wnioski/${id}/zatwierdz`} className="btn-warning">Zatwierdź</Link>
          )}
          {wniosek.status === 'SZKIC' && (
            <Link to={`/wnioski/nowy?pracownik_id=${wniosek.pracownik_id}`} className="btn-secondary">Edytuj szkic</Link>
          )}
          {wniosek.pdf_sciezka && (
            <a href={`/api/wnioski/${id}/pdf`} target="_blank" rel="noreferrer" className="btn-secondary">
              Pobierz PDF
            </a>
          )}
        </div>
      </div>

      {/* Workflow path */}
      {wniosek.etapy?.length > 0 && (
        <div className="card p-4">
          <h3 className="text-sm font-semibold text-gray-600 mb-3">Ścieżka zatwierdzania</h3>
          <WorkflowVisualizer etapy={wniosek.etapy} aktualnyEtap={wniosek.aktualny_etap_kolejnosc} />
        </div>
      )}

      {/* Employee info */}
      <div className="card p-5">
        <h3 className="font-semibold mb-3">Dane pracownika</h3>
        <div className="grid grid-cols-2 gap-x-8 gap-y-2 text-sm">
          <div><span className="text-gray-500">Imię i nazwisko:</span> <span className="font-medium">{wniosek.pracownik_nazwa}</span></div>
          <div><span className="text-gray-500">Stanowisko:</span> <span>{wniosek.stanowisko || '—'}</span></div>
          <div><span className="text-gray-500">Komórka:</span> <span>{wniosek.komorka_nazwa || '—'}</span></div>
          <div><span className="text-gray-500">Inicjujący:</span> <span>{wniosek.inicjujacy_nazwa}</span></div>
        </div>
        {wniosek.uwagi_inicjujacego && (
          <div className="mt-3 p-3 bg-gray-50 rounded text-sm">
            <span className="text-gray-500 font-medium">Uwagi: </span>{wniosek.uwagi_inicjujacego}
          </div>
        )}
      </div>

      {/* Positions */}
      <div className="card">
        <div className="px-5 py-4 border-b">
          <h3 className="font-semibold">Wnioskowane uprawnienia ({wniosek.pozycje?.length || 0})</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-100">
            <thead className="bg-gray-50">
              <tr>
                {['System', 'Moduł', 'Zakres', 'Uprzywilejowany', 'Uzasadnienie'].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-600 uppercase">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {wniosek.pozycje?.map(p => (
                <tr key={p.id}>
                  <td className="px-4 py-3 text-sm font-medium">{p.system_nazwa}</td>
                  <td className="px-4 py-3 text-sm text-gray-500">{p.modul_nazwa || '—'}</td>
                  <td className="px-4 py-3 text-sm">{p.zakres_nazwa}</td>
                  <td className="px-4 py-3 text-sm">
                    {p.uprzywilejowany ? <span className="badge-red">TAK ⚠</span> : <span className="badge-gray">NIE</span>}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-500">{p.uzasadnienie || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Approval history */}
      {wniosek.etapy?.length > 0 && (
        <div className="card p-5">
          <h3 className="font-semibold mb-3">Historia zatwierdzeń</h3>
          <div className="space-y-2">
            {wniosek.etapy.map(e => (
              <div key={e.id} className="flex items-center gap-4 text-sm">
                <span className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold
                  ${e.status === 'ZATWIERDZONY' ? 'bg-green-100 text-green-700' :
                    e.status === 'ODRZUCONY' ? 'bg-red-100 text-red-700' :
                    e.status === 'OCZEKUJE' ? 'bg-yellow-100 text-yellow-700' :
                    'bg-gray-100 text-gray-600'}`}>
                  {e.kolejnosc}
                </span>
                <span className="font-medium w-40">{e.nazwa || `Etap ${e.kolejnosc}`}</span>
                <span className="text-gray-500">{e.zatwierdzajacy_nazwa || '—'}</span>
                <span className={`ml-auto badge ${
                  e.status === 'ZATWIERDZONY' ? 'badge-green' :
                  e.status === 'ODRZUCONY' ? 'badge-red' :
                  e.status === 'OCZEKUJE' ? 'badge-yellow' :
                  e.status === 'POMINIĘTY' ? 'badge-gray' : 'badge-blue'}`}>
                  {e.status}
                </span>
                {e.data_akcji && <span className="text-gray-400">{new Date(e.data_akcji).toLocaleDateString('pl-PL')}</span>}
                {e.komentarz && <span className="text-gray-500 truncate max-w-[200px]" title={e.komentarz}>"{e.komentarz}"</span>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* IT section */}
      {isIT && wniosek.status === 'OCZEKUJE_IT' && (
        <div className="card p-5 border-purple-200 bg-purple-50">
          <h3 className="font-semibold text-purple-900 mb-2">Realizacja IT</h3>
          <p className="text-sm text-purple-700 mb-4">Wniosek zatwierdził(a) proces zatwierdzania. Po realizacji uprawnienia zostaną nadane.</p>
          <Link to={`/wnioski/${id}/zatwierdz`} className="btn-primary">Realizuj wniosek</Link>
        </div>
      )}

      {wniosek.powod_odrzucenia && (
        <div className="card p-5 border-red-200 bg-red-50">
          <h3 className="font-semibold text-red-800 mb-1">Powód odrzucenia</h3>
          <p className="text-sm text-red-700">{wniosek.powod_odrzucenia}</p>
        </div>
      )}

      <Link to="/wnioski" className="text-sm text-gray-500 hover:text-gray-700">← Powrót do listy</Link>
    </div>
  );
}
