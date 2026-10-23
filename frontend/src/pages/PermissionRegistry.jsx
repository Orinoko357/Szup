import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  RefreshCw, Download, Search, X, FileText, PlayCircle,
} from 'lucide-react'
import {
  listGrantedRegistry, grantedRegistryCsvUrl, getDeclaration,
  listActiveUnits, listSystems,
  listSnapshots, getSnapshot, snapshotCsvUrl, runSnapshot,
 errorMessage} from '../api'
import { fmtDate } from '../serverTime'
import { toast } from '../components/ui/feedback'
import Modal from '../components/ui/Modal'
import { LoadError } from '../components/ui/LoadState'
import { getUserRoles, hasAnyRole } from '../roles'

/**
 * Rejestr uprawnień — dwie zakładki:
 *   - „Stan bieżący": nadane uprawnienia z wniosków, z kolumną oświadczenia,
 *   - „Migawki 23:50": historyczne, nocne migawki „kto co miał danego dnia".
 */
export default function PermissionRegistry() {
  const [mode, setMode] = useState('current')

  const isAdmin = hasAnyRole(getUserRoles(), ['admin', 'superadmin'])

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-header__title">Rejestr uprawnień</h1>
          <div className="page-header__sub">
            Nadane uprawnienia i historyczne migawki stanu — do audytu (NIS2 / KSC / RODO)
          </div>
        </div>
      </div>

      <div className="tabs" role="tablist" aria-label="Widok rejestru" style={{ marginTop: 0 }}>
        <button role="tab" aria-selected={mode === 'current'}
                className={`tab-btn${mode === 'current' ? ' active' : ''}`}
                onClick={() => setMode('current')}>
          Stan bieżący
        </button>
        <button role="tab" aria-selected={mode === 'snapshots'}
                className={`tab-btn${mode === 'snapshots' ? ' active' : ''}`}
                onClick={() => setMode('snapshots')}>
          Migawki 23:50
        </button>
      </div>

      {mode === 'current' ? <CurrentRegistry /> : <SnapshotsRegistry isAdmin={isAdmin} />}
    </div>
  )
}


/** Podgląd zamrożonej treści oświadczenia (wspólny dla obu zakładek). */
function DeclarationDetail({ detail, onClose }) {
  if (!detail) return null
  return (
    <Modal title={`Oświadczenie — ${detail.reference_code}`} onClose={onClose} width={760}>
      <div style={{ fontSize: 12.5, color: 'var(--color-text-muted)', marginBottom: 10 }}>
        Pracownik: <strong style={{ color: 'var(--color-text)' }}>{detail.worker_name}</strong>{' · '}
        Wniosek #{detail.request_id}{' · '}
        Złożono: <strong style={{ color: 'var(--color-text)' }}>{detail.declared_by_name}</strong>,
        {' '}{detail.declared_date}
      </div>
      <div style={{
        fontSize: 12.5, lineHeight: 1.55, whiteSpace: 'pre-wrap',
        border: '1px solid var(--color-border)', borderRadius: 6,
        padding: '12px 14px', background: 'var(--bg-secondary)',
      }}>
        {detail.declaration_text}
      </div>
    </Modal>
  )
}


function CurrentRegistry() {
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)
  const [units, setUnits] = useState([])
  const [systems, setSystems] = useState([])
  const [detail, setDetail] = useState(null)
  // ?q= — wejście z wyszukiwarki globalnej (Ctrl+K) od razu filtruje po pracowniku.
  const [f, setF] = useState(() => ({ unit_id: '', system_id: '',
    q: new URLSearchParams(window.location.search).get('q') || '', only_with_declaration: false }))

  const params = () => ({
    ...(f.unit_id ? { unit_id: f.unit_id } : {}),
    ...(f.system_id ? { system_id: f.system_id } : {}),
    ...(f.q.trim() ? { q: f.q.trim() } : {}),
    ...(f.only_with_declaration ? { only_with_declaration: true } : {}),
  })

  async function load() {
    setLoading(true); setErr(null)
    try {
      const r = await listGrantedRegistry({ ...params(), limit: 500 })
      setRows(r.data.items || []); setTotal(r.data.total || 0)
    } catch (ex) {
      // Bez catch wyjątek szedł w próżnię (nieobsłużone odrzucenie), a ekran
      // pokazywał „Brak nadanych uprawnień”.
      setErr(errorMessage(ex, 'Nie udało się wczytać rejestru uprawnień'))
      setRows([]); setTotal(0)
    } finally { setLoading(false) }
  }

  useEffect(() => {
    listActiveUnits().then(r => setUnits(r.data))
      .catch(ex => toast(errorMessage(ex, 'Nie udało się wczytać listy jednostek'), { tone: 'error' }))
    listSystems().then(r => setSystems(r.data))
      .catch(ex => toast(errorMessage(ex, 'Nie udało się wczytać listy systemów'), { tone: 'error' }))
  }, [])
  useEffect(() => { load() }, [f.unit_id, f.system_id, f.only_with_declaration])

  // Ponowne wyszukanie z wyszukiwarki globalnej na tej samej stronie (?q=…)
  // zmienia filtr i odświeża listę.
  const [searchParams] = useSearchParams()
  const urlQ = searchParams.get('q') || ''
  useEffect(() => {
    if (urlQ && urlQ !== f.q) setF(prev => ({ ...prev, q: urlQ }))
  }, [urlQ])
  useEffect(() => { if (urlQ && f.q === urlQ) load() }, [f.q === urlQ ? urlQ : null])

  const hasFilter = f.unit_id || f.system_id || f.q.trim() || f.only_with_declaration

  return (
    <>
      <section className="card" aria-label="Filtry" style={{ marginBottom: 16, padding: '14px 16px', display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <div style={{ position: 'relative', flex: '1 1 220px' }}>
          <Search size={14} aria-hidden="true" style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--color-text-muted)' }} />
          <input className="form-control" aria-label="Szukaj pracownika" style={{ paddingLeft: 34, minHeight: 44 }}
                 placeholder="Szukaj pracownika…" value={f.q}
                 onChange={e => setF(x => ({ ...x, q: e.target.value }))}
                 onKeyDown={e => e.key === 'Enter' && load()} />
        </div>
        <select className="form-control" aria-label="Jednostka" style={{ flex: '0 1 200px', minHeight: 44 }}
                value={f.unit_id} onChange={e => setF(x => ({ ...x, unit_id: e.target.value }))}>
          <option value="">Wszystkie jednostki</option>
          {units.map(u => <option key={u.id} value={u.id}>{u.name}</option>)}
        </select>
        <select className="form-control" aria-label="System" style={{ flex: '0 1 200px', minHeight: 44 }}
                value={f.system_id} onChange={e => setF(x => ({ ...x, system_id: e.target.value }))}>
          <option value="">Wszystkie systemy</option>
          {systems.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        <label style={{ display: 'inline-flex', alignItems: 'center', gap: 8, minHeight: 44, fontSize: 14, cursor: 'pointer' }}>
          <input type="checkbox" style={{ width: 18, height: 18, accentColor: 'var(--color-selected)' }} checked={f.only_with_declaration}
                 onChange={e => setF(x => ({ ...x, only_with_declaration: e.target.checked }))} />
          Tylko z oświadczeniem
        </label>
        {hasFilter && (
          <button className="btn btn--ghost btn--sm"
                  onClick={() => setF({ unit_id: '', system_id: '', q: '', only_with_declaration: false })}>
            <X size={12} /> Wyczyść
          </button>
        )}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
          {!err && <span style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>Pozycji: <strong style={{ color: 'var(--color-heading)' }}>{total}</strong></span>}
          <a className="btn btn--ghost btn--sm" href={grantedRegistryCsvUrl(params())}
             target="_blank" rel="noopener noreferrer">
            <Download size={14} /> CSV
          </a>
          <button className="btn btn--ghost btn--sm" onClick={load} disabled={loading}>
            <RefreshCw size={14} /> Odśwież
          </button>
        </div>
      </section>

      {!loading && !err && total > rows.length && rows.length > 0 && (
        <div className="alert alert--info" role="status" style={{ marginBottom: 12 }}>
          Pokazano {rows.length} z {total} — zawęź filtr (jednostka, system, wyszukiwanie), aby zobaczyć resztę,
          albo pobierz pełny CSV.
        </div>
      )}
      <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
        {loading ? (
          <div style={{ color: 'var(--color-text-muted)', padding: 16 }}>Ładowanie…</div>
        ) : err ? (
          <LoadError message={err} onRetry={load} />
        ) : rows.length === 0 ? (
          <div style={{ color: 'var(--color-text-muted)', padding: 16 }}>Brak nadanych uprawnień.</div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Pracownik</th><th>Jednostka / wydział</th><th>System</th>
                <th>Uprawnienie</th><th>Data nadania</th><th>Oświadczenie</th><th>Kod</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td style={{ fontWeight: 600 }}>{r.worker_name}</td>
                  <td style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>
                    {r.unit_name || '—'}{r.department_name ? ` / ${r.department_name}` : ''}
                  </td>
                  <td>{r.system_name || '—'}</td>
                  <td>
                    {r.group_name && <span className="badge badge--neutral" style={{ borderRadius: 4, fontSize: 11, fontWeight: 700, marginRight: 6 }}>{r.group_name}</span>}
                    <span style={{ fontWeight: 600, textDecoration: r.revoked ? 'line-through' : 'none' }}>{r.permission_name || '—'}</span>
                    {r.revoked && (
                      <span className="badge badge--error" style={{ fontSize: 11, marginLeft: 6 }}
                            title={r.revoked_at ? `Odebrano ${fmtDate(r.revoked_at)}` : undefined}>
                        odebrane{r.revoked_by_request_id ? ` (#${r.revoked_by_request_id})` : ''}
                      </span>
                    )}
                    {r.custom_values && Object.keys(r.custom_values).length > 0 && (
                      <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                        {Object.entries(r.custom_values).map(([k, v]) => `${k}: ${v}`).join(' · ')}
                      </div>
                    )}
                  </td>
                  <td style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>{r.granted_at ? fmtDate(r.granted_at) : '—'}</td>
                  <td style={{ fontSize: 13 }}>
                    {r.declared_by_name ? (
                      <><div style={{ fontWeight: 600 }}>{r.declared_by_name}</div>
                        <div style={{ color: 'var(--color-text-muted)' }}>{r.declared_date || (r.declaration_at ? fmtDate(r.declaration_at) : '')}</div></>
                    ) : <span className="badge badge--neutral" style={{ fontWeight: 700 }} title="Nadanie sprzed wdrożenia oświadczeń">brak</span>}
                  </td>
                  <td>
                    {r.reference_code ? (
                      <button className="btn btn--ghost btn--sm" style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}
                              title="Podgląd oświadczenia"
                              onClick={() => getDeclaration(r.reference_code).then(x => setDetail(x.data))
                                .catch(ex => toast(errorMessage(ex, 'Nie udało się wczytać oświadczenia'), { tone: 'error' }))}>
                        <FileText size={11} /> {r.reference_code}
                      </button>
                    ) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <DeclarationDetail detail={detail} onClose={() => setDetail(null)} />
    </>
  )
}


function SnapshotsRegistry({ isAdmin }) {
  const [list, setList] = useState([])
  const [date, setDate] = useState('')
  const [snap, setSnap] = useState(null)
  const [q, setQ] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  async function loadList(selectFirst = false) {
    setLoading(true); setErr(null)
    try {
      const r = await listSnapshots()
      const items = r.data.items || []
      setList(items)
      if (selectFirst && items.length && !date) setDate(items[0].snapshot_date)
    } catch (ex) {
      setErr(errorMessage(ex, 'Nie udało się wczytać listy migawek'))
    } finally { setLoading(false) }
  }

  useEffect(() => { loadList(true) }, [])

  async function loadSnap(d, query = '') {
    if (!d) { setSnap(null); return }
    try {
      const r = await getSnapshot(d, query.trim() ? { q: query.trim() } : {})
      setSnap(r.data); setErr(null)
    } catch (ex) {
      setSnap(null)
      setErr(errorMessage(ex, `Nie udało się wczytać migawki z ${d}`))
    }
  }
  useEffect(() => { loadSnap(date, q) }, [date])

  async function generateNow() {
    setBusy(true)
    try {
      const r = await runSnapshot(false)
      await loadList()
      setDate(r.data.snapshot_date)
    } catch (ex) {
      toast(errorMessage(ex, 'Nie udało się wygenerować migawki'), { tone: 'error' })
    } finally { setBusy(false) }
  }

  const meta = list.find(s => s.snapshot_date === date)

  return (
    <>
      <div className="alert alert--info" style={{ fontSize: 13, marginBottom: 16 }}>
        Migawki tworzą się <strong>automatycznie codziennie o 23:50</strong> i pozostają
        dostępne bezterminowo (retencja ≥ 5 lat) — pozwalają odtworzyć, kto jakie
        uprawnienia miał danego dnia. Każda migawka ma sumę kontrolną SHA-256.
      </div>

      <section className="card" aria-label="Filtry" style={{ marginBottom: 16, padding: '14px 16px', display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <label htmlFor="snap-day" style={{ fontSize: 14, fontWeight: 700 }}>Dzień:</label>
        <select id="snap-day" className="form-control" style={{ flex: '0 1 300px', minHeight: 44 }}
                value={date} onChange={e => setDate(e.target.value)}>
          {list.length === 0 && <option value="">— brak migawek —</option>}
          {list.map(s => (
            <option key={s.snapshot_date} value={s.snapshot_date}>
              {s.snapshot_date} · {s.person_count} osób / {s.permission_count} pozycji
            </option>
          ))}
        </select>
        <div style={{ position: 'relative', flex: '1 1 200px' }}>
          <Search size={14} aria-hidden="true" style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--color-text-muted)' }} />
          <input className="form-control" aria-label="Szukaj pracownika" style={{ paddingLeft: 34, minHeight: 44 }}
                 placeholder="Szukaj pracownika…" value={q}
                 onChange={e => setQ(e.target.value)}
                 onKeyDown={e => e.key === 'Enter' && loadSnap(date, q)} />
        </div>
        <button className="btn btn--ghost btn--sm" onClick={() => loadSnap(date, q)} disabled={!date}>
          Szukaj
        </button>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
          {date && (
            <a className="btn btn--ghost btn--sm"
               href={snapshotCsvUrl(date, q.trim() ? { q: q.trim() } : {})}
               target="_blank" rel="noopener noreferrer">
              <Download size={14} /> CSV
            </a>
          )}
          {isAdmin && (
            <button className="btn btn--primary btn--sm" onClick={generateNow} disabled={busy}>
              <PlayCircle size={14} /> {busy ? 'Generowanie…' : 'Generuj teraz'}
            </button>
          )}
          <button className="btn btn--ghost btn--sm" onClick={() => loadList()} disabled={loading}>
            <RefreshCw size={14} /> Odśwież
          </button>
        </div>
      </section>

      {meta && (
        <div style={{ fontSize: 12, fontFamily: 'var(--font-mono)', color: 'var(--color-text-muted)', margin: '0 2px 12px' }}>
          Migawka z {fmtDate(meta.created_at)} · autor: {meta.generated_by} ·
          {' '}SHA-256: <span style={{ fontFamily: 'var(--font-mono)' }}>{meta.content_sha256.slice(0, 16)}…</span>
        </div>
      )}

      <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
        {loading ? (
          <div style={{ color: 'var(--color-text-muted)', padding: 16 }}>Ładowanie…</div>
        ) : err ? (
          <LoadError message={err} onRetry={() => { loadList(); loadSnap(date, q) }} />
        ) : !snap ? (
          <div style={{ color: 'var(--color-text-muted)', padding: 16 }}>
            Brak migawek. Pierwsza powstanie automatycznie o 23:50{isAdmin ? ' albo użyj „Generuj teraz".' : '.'}
          </div>
        ) : snap.rows.length === 0 ? (
          <div style={{ color: 'var(--color-text-muted)', padding: 16 }}>Brak pozycji w tej migawce.</div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Pracownik</th><th>Jednostka / wydział</th><th>System</th>
                <th>Uprawnienie</th><th>Kod oświadczenia</th>
              </tr>
            </thead>
            <tbody>
              {snap.rows.map((r, i) => (
                <tr key={i}>
                  <td style={{ fontWeight: 600 }}>{r.worker_name}
                    <span style={{ color: 'var(--color-text-muted)', fontWeight: 400, fontSize: 12 }}> ({r.username})</span>
                  </td>
                  <td style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>
                    {r.unit_name || '—'}{r.department_name ? ` / ${r.department_name}` : ''}
                  </td>
                  <td>{r.system_name || '—'}</td>
                  <td>
                    {r.permission_name || '—'}
                    {r.custom_values && Object.keys(r.custom_values).length > 0 && (
                      <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                        {Object.entries(r.custom_values).map(([k, v]) => `${k}: ${v}`).join(' · ')}
                      </div>
                    )}
                  </td>
                  <td style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>{r.reference_code || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  )
}
