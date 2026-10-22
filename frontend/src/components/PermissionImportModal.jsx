import { useState } from 'react'
import { Upload, X, Check, ClipboardPaste, FileSpreadsheet, AlertTriangle } from 'lucide-react'
import { previewPermissionImport, commitPermissionImport } from '../api'

/**
 * Import listy uprawnień dla oprogramowania — z pliku (CSV / TSV / Excel / PDF)
 * albo z wklejenia ze schowka.
 *
 * Trzy kroki, bo lista z systemu dziedzinowego to setki pozycji i nikt nie
 * zaakceptuje ich w ciemno:
 *   1. źródło        — plik lub wklejone dane,
 *   2. mapowanie     — które kolumny to symbol / nazwa / opis + nazwa grupy,
 *   3. korekta       — edytowalna tabela wszystkich pozycji przed zapisem.
 *
 * Krok 2 odpytuje backend ponownie przy każdej zmianie ról kolumn — składanie
 * nazwy („SYMBOL - Nazwa") ma JEDNO źródło prawdy po stronie serwera.
 * Krok 3 zapisuje dokładnie to, co widać na ekranie: commit nie parsuje już
 * niczego, więc nie da się zapisać czegoś innego niż zatwierdzone.
 */
const ROLE_LABELS = {
  ignore: 'pomiń',
  code: 'symbol / kod',
  name: 'nazwa uprawnienia',
  description: 'opis',
}

const STATUS_BADGE = {
  new: ['badge--success', 'nowe'],
  existing: ['badge--info', 'istnieje'],
  reactivate: ['badge--warning', 'przywrócenie'],
}

export default function PermissionImportModal({ system, onClose, onDone }) {
  const [step, setStep] = useState(1)
  const [file, setFile] = useState(null)
  const [pasted, setPasted] = useState('')
  const [columns, setColumns] = useState([])
  const [group, setGroup] = useState('')
  const [items, setItems] = useState([])          // { name, description, code, use }
  const [warnings, setWarnings] = useState([])
  const [existingInGroup, setExistingInGroup] = useState(0)
  const [deactivateMissing, setDeactivateMissing] = useState(true)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [result, setResult] = useState(null)

  /** Wspólne wywołanie preview — używane i przy wejściu, i przy zmianie mapowania. */
  async function runPreview(roles, groupName) {
    setBusy(true); setErr(null)
    try {
      const fd = new FormData()
      if (file) fd.append('file', file)
      if (pasted.trim()) fd.append('pasted', pasted)
      if (roles) fd.append('roles', JSON.stringify(roles))
      if (groupName) fd.append('group_name', groupName)

      const r = await previewPermissionImport(system.id, fd)
      const d = r.data
      setColumns(d.columns)
      setWarnings(d.warnings || [])
      setExistingInGroup(d.existing_in_group || 0)
      if (!groupName) setGroup(d.group_suggested || '')
      setItems(d.items.map(i => ({
        name: i.permission_name,
        description: i.description || '',
        code: i.external_code || '',
        status: i.status,
        use: true,
      })))
      return true
    } catch (ex) {
      setErr(ex.response?.data?.detail || 'Nie udało się odczytać pliku')
      return false
    } finally {
      setBusy(false)
    }
  }

  async function start() {
    if (!file && !pasted.trim()) {
      setErr('Wskaż plik albo wklej dane ze schowka.'); return
    }
    if (await runPreview(null, null)) setStep(2)
  }

  /**
   * Zmiana roli kolumny. Backend dostaje role dla WSZYSTKICH indeksów kolumn,
   * bo lista `columns` pomija kolumny puste — indeksy muszą się zgadzać.
   */
  async function setRole(index, role) {
    const next = columns.map(c => (c.index === index ? { ...c, role } : c))
    setColumns(next)
    const width = Math.max(...next.map(c => c.index)) + 1
    const roles = Array.from({ length: width }, (_, i) =>
      next.find(c => c.index === i)?.role || 'ignore')
    await runPreview(roles, group)
  }

  async function save() {
    const chosen = items.filter(i => i.use && i.name.trim())
    if (!group.trim()) { setErr('Podaj nazwę grupy uprawnień.'); return }
    if (chosen.length === 0) { setErr('Nie zaznaczono żadnej pozycji.'); return }

    setBusy(true); setErr(null)
    try {
      const r = await commitPermissionImport(system.id, {
        group_name: group.trim(),
        deactivate_missing: deactivateMissing,
        items: chosen.map(i => ({
          permission_name: i.name.trim(),
          description: i.description.trim() || null,
          external_code: i.code.trim() || null,
        })),
      })
      setResult(r.data)
      setStep(4)
    } catch (ex) {
      setErr(ex.response?.data?.detail || 'Nie udało się zapisać uprawnień')
    } finally {
      setBusy(false)
    }
  }

  const chosenCount = items.filter(i => i.use && i.name.trim()).length
  // Ile istniejących pozycji grupy zniknie z wniosków po zapisie.
  const toDeactivate = Math.max(
    0, existingInGroup - items.filter(i => i.use && i.status !== 'new').length)

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth: 900, width: '92vw' }}>
        <div className="modal__header" style={{ background: 'var(--color-card)', color: 'var(--color-heading)', padding: '12px 12px 12px 20px', gap: 12 }}>
          <h2 style={{ flex: 1, margin: 0, fontSize: 18, fontWeight: 800, color: 'var(--color-heading)' }}>
            Import uprawnień — {system.name}
          </h2>
          <button type="button" onClick={onClose} aria-label="Zamknij" title="Zamknij"
                  style={{ width: 44, height: 44, display: 'grid', placeItems: 'center', border: 0, borderRadius: 8,
                           background: 'transparent', color: 'var(--color-text-muted)', cursor: 'pointer', flexShrink: 0 }}>
            <X size={18} />
          </button>
        </div>

        <div className="modal__body" style={{ maxHeight: '70vh', overflowY: 'auto' }}>
          {err && <div className="alert alert--error mb-4">{err}</div>}

          {step === 1 && (
            <>
              <div className="form-group">
                <label className="form-label">Plik z listą uprawnień</label>
                <input type="file" className="form-control"
                       accept=".csv,.txt,.tsv,.xls,.xlsx,.xlsm,.pdf"
                       onChange={e => { setFile(e.target.files?.[0] || null); setPasted('') }} />
                <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 4 }}>
                  Obsługiwane: CSV, TSV, Excel (.xls, .xlsx) i PDF z wydrukiem
                  listy. Nagłówek raportu, numeracja i stopki są odrzucane
                  automatycznie, a symbol i nazwa łączone w „SYMBOL - Nazwa".
                </div>
              </div>

              <div style={{
                textAlign: 'center', margin: '10px 0', fontSize: 12,
                color: 'var(--color-text-muted)',
              }}>
                — albo —
              </div>

              <div className="form-group">
                <label className="form-label" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <ClipboardPaste size={14} /> Wklej dane ze schowka
                </label>
                <textarea className="form-control" style={{ minHeight: 140, fontFamily: 'var(--font-mono)', fontSize: 12 }}
                          placeholder={'W programie/Excelu zaznacz listę (Ctrl+A), skopiuj (Ctrl+C) i wklej tutaj.'}
                          value={pasted}
                          onChange={e => { setPasted(e.target.value); setFile(null) }} />
              </div>
            </>
          )}

          {step === 2 && (
            <>
              <div className="form-group">
                <label className="form-label">Nazwa grupy uprawnień</label>
                <input className="form-control" style={{ maxWidth: 460 }}
                       value={group} onChange={e => setGroup(e.target.value)}
                       placeholder="np. Rejestry opłat" />
                <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 4 }}>
                  Jedno oprogramowanie może mieć kilka grup — każda z osobnego pliku.
                  Ponowny import tej samej grupy aktualizuje jej pozycje.
                  {existingInGroup > 0 && (
                    <> Ta grupa ma już <strong>{existingInGroup}</strong> pozycji.</>
                  )}
                </div>
              </div>

              <div className="form-label" style={{ marginTop: 12 }}>Kolumny</div>
              <table className="data-table" style={{ marginBottom: 12 }}>
                <thead>
                  <tr>
                    <th style={{ width: '28%' }}>Nagłówek</th>
                    <th>Przykładowe wartości</th>
                    <th style={{ width: 190 }}>Rola</th>
                  </tr>
                </thead>
                <tbody>
                  {columns.map(c => (
                    <tr key={c.index}>
                      <td style={{ fontWeight: 600 }}>{c.header}</td>
                      <td style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>
                        {c.samples.join(' · ') || '—'}
                      </td>
                      <td>
                        <select className="form-control" style={{ fontSize: 12 }}
                                value={c.role} disabled={busy}
                                onChange={e => setRole(c.index, e.target.value)}>
                          {Object.entries(ROLE_LABELS).map(([v, l]) => (
                            <option key={v} value={v}>{l}</option>
                          ))}
                        </select>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <div className="alert alert--info" style={{ fontSize: 12 }}>
                Podgląd złożonych nazw:
                <ul style={{ margin: '6px 0 0 18px' }}>
                  {items.slice(0, 3).map((i, n) => <li key={n}>{i.name}</li>)}
                </ul>
                Razem pozycji: <strong>{items.length}</strong>
              </div>

              {warnings.map((w, n) => (
                <div key={n} className="alert alert--warning" style={{ fontSize: 12 }}>
                  <AlertTriangle size={13} style={{ verticalAlign: 'middle', marginRight: 6 }} />
                  {w}
                </div>
              ))}
            </>
          )}

          {step === 3 && (
            <>
              <div style={{
                display: 'flex', alignItems: 'center', gap: 12,
                marginBottom: 10, flexWrap: 'wrap',
              }}>
                <strong>Grupa: {group}</strong>
                <span className="badge badge--info">do zapisania: {chosenCount}</span>
                <button className="btn btn--ghost btn--sm"
                        onClick={() => setItems(x => x.map(i => ({ ...i, use: true })))}>
                  Zaznacz wszystkie
                </button>
                <button className="btn btn--ghost btn--sm"
                        onClick={() => setItems(x => x.map(i => ({ ...i, use: false })))}>
                  Odznacz wszystkie
                </button>
              </div>

              <table className="data-table">
                <thead>
                  <tr>
                    <th style={{ width: 34 }}></th>
                    <th style={{ width: 90 }}>Symbol</th>
                    <th>Nazwa uprawnienia</th>
                    <th style={{ width: '25%' }}>Opis</th>
                    <th style={{ width: 110 }}>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((i, n) => (
                    <tr key={n} style={{ opacity: i.use ? 1 : 0.45 }}>
                      <td>
                        <input type="checkbox" checked={i.use}
                               onChange={e => setItems(x => x.map(
                                 (y, m) => (m === n ? { ...y, use: e.target.checked } : y)))} />
                      </td>
                      <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                        {i.code || '—'}
                      </td>
                      <td>
                        <input className="form-control" style={{ fontSize: 12 }}
                               value={i.name}
                               onChange={e => setItems(x => x.map(
                                 (y, m) => (m === n ? { ...y, name: e.target.value } : y)))} />
                      </td>
                      <td>
                        <input className="form-control" style={{ fontSize: 12 }}
                               value={i.description}
                               onChange={e => setItems(x => x.map(
                                 (y, m) => (m === n ? { ...y, description: e.target.value } : y)))} />
                      </td>
                      <td>
                        <span className={`badge ${STATUS_BADGE[i.status]?.[0] || 'badge--neutral'}`}
                              style={{ fontSize: 10 }}>
                          {STATUS_BADGE[i.status]?.[1] || i.status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <label style={{
                display: 'flex', alignItems: 'center', gap: 8,
                marginTop: 12, fontSize: 13, cursor: 'pointer',
              }}>
                <input type="checkbox" checked={deactivateMissing}
                       onChange={e => setDeactivateMissing(e.target.checked)} />
                Wygaś pozycje tej grupy, których nie ma w pliku
                {toDeactivate > 0 && (
                  <span className="badge badge--warning" style={{ fontSize: 10 }}>
                    dotyczy {toDeactivate}
                  </span>
                )}
              </label>
              <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginLeft: 24 }}>
                Wygaszone uprawnienia znikają z nowych wniosków, ale zostają
                w historii i w ewidencji osób, które je posiadają.
              </div>
            </>
          )}

          {step === 4 && result && (
            <div className="alert alert--success">
              <div><strong>Import zakończony.</strong></div>
              <ul style={{ margin: '6px 0 0 18px' }}>
                <li>dodano: {result.added}</li>
                <li>przywrócono: {result.reactivated}</li>
                <li>zaktualizowano: {result.updated}</li>
                <li>wygaszono: {result.deactivated}</li>
                {result.skipped > 0 && <li>pominięto: {result.skipped}</li>}
              </ul>
            </div>
          )}
        </div>

        <div className="modal__footer" style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          {step === 4 ? (
            <button className="btn btn--primary btn--sm" onClick={onDone}>
              <Check size={13} /> Zamknij
            </button>
          ) : (
            <>
              <button className="btn btn--ghost btn--sm" onClick={onClose} disabled={busy}>
                Anuluj
              </button>
              {step > 1 && (
                <button className="btn btn--ghost btn--sm" disabled={busy}
                        onClick={() => setStep(step - 1)}>
                  Wstecz
                </button>
              )}
              {step === 1 && (
                <button className="btn btn--primary btn--sm" onClick={start} disabled={busy}>
                  <Upload size={13} /> {busy ? 'Czytam…' : 'Wczytaj'}
                </button>
              )}
              {step === 2 && (
                <button className="btn btn--primary btn--sm" disabled={busy || !group.trim()}
                        onClick={() => setStep(3)}>
                  Dalej — sprawdź pozycje
                </button>
              )}
              {step === 3 && (
                <button className="btn btn--primary btn--sm" onClick={save} disabled={busy}>
                  <Check size={13} /> {busy ? 'Zapisuję…' : `Zapisz ${chosenCount} pozycji`}
                </button>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
