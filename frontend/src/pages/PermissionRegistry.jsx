import { useEffect, useState } from 'react'
import {
  ClipboardList, RefreshCw, Download, Search, X, FileText, Camera, PlayCircle,
} from 'lucide-react'
import {
  listGrantedRegistry, grantedRegistryCsvUrl, getDeclaration,
  listActiveUnits, listSystems,
  listSnapshots, getSnapshot, snapshotCsvUrl, runSnapshot,
} from '../api'
import { fmtDate } from '../serverTime'

/**
 * Rejestr uprawnień — dwie zakładki:
 *   - „Stan bieżący": nadane uprawnienia z wniosków, z kolumną oświadczenia,
 *   - „Migawki 23:50": historyczne, nocne migawki „kto co miał danego dnia".
 */
export default function PermissionRegistry() {
  const [mode, setMode] = useState('current')

  const isAdmin = (() => {
    try {
      const u = JSON.parse(localStorage.getItem('szup_user') || '{}')
      const roles = Array.isArray(u.roles) ? u.roles : (u.role ? [u.role] : [])
      return roles.includes('admin') || roles.includes('superadmin')
    } catch { return false }
  })()

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-header__title">
            <ClipboardList size={18} style={{ verticalAlign: 'middle', marginRight: 8 }} />
            Rejestr uprawnień
          </div>
          <div className="page-header__sub">
            Nadane uprawnienia i historyczne migawki stanu — do audytu (NIS2 / KSC / RODO)
          </div>
        </div>
      </div>

      <div className="tabs" style={{ marginTop: 0 }}>
        <button className={`tab-btn${mode === 'current' ? ' active' : ''}`}
                onClick={() => setMode('current')}>
          <ClipboardList size={13} /> Stan bieżący
        </button>
        <button className={`tab-btn${mode === 'snapshots' ? ' active' : ''}`}
                onClick={() => setMode('snapshots')}>
          <Camera size={13} /> Migawki 23:50
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
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth: 760, width: '92vw' }}>
        <div className="modal__header">
          <div><FileText size={16} style={{ verticalAlign: 'middle', marginRight: 6 }} />
            Oświadczenie — {detail.reference_code}</div>
          <button className="btn btn--ghost btn--sm" onClick={onClose}><X size={14} /></button>
        </div>
        <div className="modal__body" style={{ maxHeight: '72vh', overflowY: 'auto' }}>
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
        </div>
      </div>
    </div>
  )
}


function CurrentRegistry() {
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [units, setUnits] = useState([])
  const [systems, setSystems] = useState([])
  const [detail, setDetail] = useState(null)
  const [f, setF] = useState({ unit_id: '', system_id: '', q: '', only_with_declaration: false })

  const params = () => ({
    ...(f.unit_id ? { unit_id: f.unit_id } : {}),
    ...(f.system_id ? { system_id: f.system_id } : {}),
    ...(f.q.trim() ? { q: f.q.trim() } : {}),
    ...(f.only_with_declaration ? { only_with_declaration: true } : {}),
  })

  async function load() {
    setLoading(true)
    try {
      const r = await listGrantedRegistry({ ...params(), limit: 500 })
      setRows(r.data.items || []); setTotal(r.data.total || 0)
    } finally { setLoading(false) }
  }

  useEffect(() => {
    listActiveUnits().then(r => setUnits(r.data)).catch(() => {})
    listSystems().then(r => setSystems(r.data)).catch(() => {})
  }, [])
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load() }, [f.unit_id, f.system_id, f.only_with_declaration])

  const hasFilter = f.unit_id || f.system_id || f.q.trim() || f.only_with_declaration

  return (
    <>
      <div className="card" style={{ marginBottom: 12, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <div style={{ position: 'relative' }}>
          <Search size={14} style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: 'var(--color-text-muted)' }} />
          <input className="form-control" style={{ paddingLeft: 30, maxWidth: 240, fontSize: 13 }}
                 placeholder="Szukaj pracownika…" value={f.q}
                 onChange={e => setF(x => ({ ...x, q: e.target.value }))}
                 onKeyDown={e => e.key === 'Enter' && load()} />
        </div>
        <select className="form-control" style={{ maxWidth: 220, fontSize: 13 }}
                value={f.unit_id} onChange={e => setF(x => ({ ...x, unit_id: e.target.value }))}>
          <option value="">Wszystkie jednostki</option>
          {units.map(u => <option key={u.id} value={u.id}>{u.name}</option>)}
        </select>
        <select className="form-control" style={{ maxWidth: 220, fontSize: 13 }}
                value={f.system_id} onChange={e => setF(x => ({ ...x, system_id: e.target.value }))}>
          <option value="">Wszystkie systemy</option>
          {systems.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer' }}>
          <input type="checkbox" checked={f.only_with_declaration}
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
          <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>Pozycji: {total}</span>
          <a className="btn btn--action btn--sm" href={grantedRegistryCsvUrl(params())}
             target="_blank" rel="noopener noreferrer">
            <Download size={14} /> CSV
          </a>
          <button className="btn btn--ghost btn--sm" onClick={load} disabled={loading}>
            <RefreshCw size={14} /> Odśwież
          </button>
        </div>
      </div>

      <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
        {loading ? (
          <div style={{ color: 'var(--color-text-muted)', padding: 16 }}>Ładowanie…</div>
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
                  <td style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
                    {r.unit_name || '—'}{r.department_name ? ` / ${r.department_name}` : ''}
                  </td>
                  <td>{r.system_name || '—'}</td>
                  <td>
                    {r.permission_name || '—'}
                    {r.group_name && <span className="badge badge--info" style={{ fontSize: 9, marginLeft: 6 }}>{r.group_name}</span>}
                    {r.custom_values && Object.keys(r.custom_values).length > 0 && (
                      <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                        {Object.entries(r.custom_values).map(([k, v]) => `${k}: ${v}`).join(' · ')}
                      </div>
                    )}
                  </td>
                  <td style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>{r.granted_at ? fmtDate(r.granted_at) : '—'}</td>
                  <td style={{ fontSize: 12 }}>
                    {r.declared_by_name ? (
                      <><div>{r.declared_by_name}</div>
                        <div style={{ color: 'var(--color-text-muted)' }}>{r.declared_date || (r.declaration_at ? fmtDate(r.declaration_at) : '')}</div></>
                    ) : <span className="badge badge--neutral" style={{ fontSize: 9 }} title="Nadanie sprzed wdrożenia oświadczeń">brak</span>}
                  </td>
                  <td>
                    {r.reference_code ? (
                      <button className="btn btn--ghost btn--sm" style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}
                              title="Podgląd oświadczenia"
                              onClick={() => getDeclaration(r.reference_code).then(x => setDetail(x.data)).catch(() => {})}>
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

  async function loadList(selectFirst = false) {
    setLoading(true)
    try {
      const r = await listSnapshots()
      const items = r.data.items || []
      setList(items)
      if (selectFirst && items.length && !date) setDate(items[0].snapshot_date)
    } finally { setLoading(false) }
  }

  useEffect(() => { loadList(true) }, [])   // eslint-disable-line react-hooks/exhaustive-deps

  async function loadSnap(d, query = '') {
    if (!d) { setSnap(null); return }
    const r = await getSnapshot(d, query.trim() ? { q: query.trim() } : {})
    setSnap(r.data)
  }
  useEffect(() => { loadSnap(date, q) }, [date])  // eslint-disable-line react-hooks/exhaustive-deps

  async function generateNow() {
    setBusy(true)
    try {
      const r = await runSnapshot(false)
      await loadList()
      setDate(r.data.snapshot_date)
    } catch (ex) {
      alert(ex.response?.data?.detail || 'Nie udało się wygenerować migawki')
    } finally { setBusy(false) }
  }

  const meta = list.find(s => s.snapshot_date === date)

  return (
    <>
      <div className="alert alert--info" style={{ fontSize: 12.5, marginBottom: 12 }}>
        Migawki tworzą się <strong>automatycznie codziennie o 23:50</strong> i pozostają
        dostępne bezterminowo (retencja ≥ 5 lat) — pozwalają odtworzyć, kto jakie
        uprawnienia miał danego dnia. Każda migawka ma sumę kontrolną SHA-256.
      </div>

      <div className="card" style={{ marginBottom: 12, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <label style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>Dzień:</label>
        <select className="form-control" style={{ maxWidth: 260, fontSize: 13 }}
                value={date} onChange={e => setDate(e.target.value)}>
          {list.length === 0 && <option value="">— brak migawek —</option>}
          {list.map(s => (
            <option key={s.snapshot_date} value={s.snapshot_date}>
              {s.snapshot_date} · {s.person_count} osób / {s.permission_count} pozycji
            </option>
          ))}
        </select>
        <div style={{ position: 'relative' }}>
          <Search size={14} style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: 'var(--color-text-muted)' }} />
          <input className="form-control" style={{ paddingLeft: 30, maxWidth: 220, fontSize: 13 }}
                 placeholder="Szukaj pracownika…" value={q}
                 onChange={e => setQ(e.target.value)}
                 onKeyDown={e => e.key === 'Enter' && loadSnap(date, q)} />
        </div>
        <button className="btn btn--ghost btn--sm" onClick={() => loadSnap(date, q)} disabled={!date}>
          Szukaj
        </button>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
          {date && (
            <a className="btn btn--action btn--sm"
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
      </div>

      {meta && (
        <div style={{ fontSize: 11.5, color: 'var(--color-text-muted)', margin: '0 2px 8px' }}>
          Migawka z {fmtDate(meta.created_at)} · autor: {meta.generated_by} ·
          {' '}SHA-256: <span style={{ fontFamily: 'var(--font-mono)' }}>{meta.content_sha256.slice(0, 16)}…</span>
        </div>
      )}

      <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
        {loading ? (
          <div style={{ color: 'var(--color-text-muted)', padding: 16 }}>Ładowanie…</div>
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
                    <span style={{ color: 'var(--color-text-muted)', fontWeight: 400, fontSize: 11 }}> ({r.username})</span>
                  </td>
                  <td style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
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
