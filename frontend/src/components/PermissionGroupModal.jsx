import { useState } from 'react'
import { X, Check, Plus, Trash2, ClipboardPaste, ListPlus } from 'lucide-react'
import { commitPermissionImport } from '../api'

/**
 * Ręczne założenie GRUPY uprawnień — bliźniacze do importu z pliku, tylko bez
 * pliku.
 *
 * Grupa to nazwana lista pozycji, z której kierownik zaznacza dowolnie wiele.
 * To jest dokładnie to samo, co „wielokrotny wybór", więc nie ma osobnego
 * mechanizmu na jedno i drugie: jeśli uprawnienie ma mieć kilka wariantów do
 * zaznaczenia, zakłada się grupę — nieważne, czy pozycje przyszły z pliku,
 * czy zostały wpisane ręcznie.
 *
 * Zapisujemy tym samym endpointem, co import (`deactivate_missing: false`,
 * bo tu nie ma pliku, względem którego można by cokolwiek wygaszać).
 */
export default function PermissionGroupModal({ system, existingGroups = [], onClose, onDone }) {
  const [group, setGroup] = useState('')
  const [rows, setRows] = useState([{ name: '', description: '' }])
  const [bulk, setBulk] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  function setRow(i, patch) {
    setRows(rs => rs.map((r, n) => (n === i ? { ...r, ...patch } : r)))
  }
  const addRow = () => setRows(rs => [...rs, { name: '', description: '' }])
  const delRow = i => setRows(rs => (rs.length > 1 ? rs.filter((_, n) => n !== i) : rs))

  /** Wklejona lista → wiersze. „Nazwa | opis" rozdziela też opis. */
  function applyBulk() {
    const parsed = bulk
      .split(/\r?\n/)
      .map(l => l.trim())
      .filter(Boolean)
      .map(l => {
        const [name, ...rest] = l.split('|')
        return { name: name.trim(), description: rest.join('|').trim() }
      })
    if (parsed.length === 0) return
    setRows(rs => {
      const kept = rs.filter(r => r.name.trim())
      return [...kept, ...parsed]
    })
    setBulk('')
  }

  const ready = rows.filter(r => r.name.trim())
  const isExisting = existingGroups.includes(group.trim())

  async function save() {
    if (!group.trim()) { setErr('Podaj nazwę grupy.'); return }
    if (ready.length === 0) { setErr('Dodaj przynajmniej jedno uprawnienie.'); return }

    setBusy(true); setErr(null)
    try {
      await commitPermissionImport(system.id, {
        group_name: group.trim(),
        deactivate_missing: false,
        items: ready.map(r => ({
          permission_name: r.name.trim(),
          description: r.description.trim() || null,
        })),
      })
      onDone()
    } catch (ex) {
      setErr(ex.response?.data?.detail || 'Nie udało się zapisać grupy')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth: 760, width: '92vw' }}>
        <div className="modal__header">
          <div>
            <ListPlus size={16} style={{ verticalAlign: 'middle', marginRight: 6 }} />
            {isExisting ? 'Dopisz do grupy' : 'Nowa grupa uprawnień'} — {system.name}
          </div>
          <button className="btn btn--ghost btn--sm" onClick={onClose}><X size={14} /></button>
        </div>

        <div className="modal__body" style={{ maxHeight: '70vh', overflowY: 'auto' }}>
          {err && <div className="alert alert--error mb-4">{err}</div>}

          <div className="form-group">
            <label className="form-label">Nazwa grupy *</label>
            <input className="form-control" style={{ maxWidth: 460 }} autoFocus
                   list="szup-existing-groups"
                   value={group} onChange={e => setGroup(e.target.value)}
                   placeholder="np. Rejestry księgowe, Moduły, Oddziały" />
            <datalist id="szup-existing-groups">
              {existingGroups.map(g => <option key={g} value={g} />)}
            </datalist>
            <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 4 }}>
              {isExisting ? (
                <>Ta grupa już istnieje — pozycje zostaną <strong>dopisane</strong> do niej.
                  Nic z niej nie zniknie.</>
              ) : (
                <>Kierownik zobaczy zwijaną sekcję o tej nazwie i zaznaczy w niej
                  dowolnie wiele pozycji — tak samo jak przy grupach z importu.
                  Wpisanie nazwy istniejącej grupy dopisze pozycje do niej.</>
              )}
            </div>
          </div>

          <div className="form-label" style={{ marginTop: 12 }}>Uprawnienia w grupie</div>
          <table className="data-table" style={{ marginBottom: 8 }}>
            <thead>
              <tr>
                <th>Nazwa</th>
                <th style={{ width: '40%' }}>Opis (opcjonalny)</th>
                <th style={{ width: 50 }}></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td>
                    <input className="form-control" style={{ fontSize: 13 }}
                           value={r.name}
                           onChange={e => setRow(i, { name: e.target.value })}
                           placeholder="np. 001 Wyciągi bankowe" />
                  </td>
                  <td>
                    <input className="form-control" style={{ fontSize: 13 }}
                           value={r.description}
                           onChange={e => setRow(i, { description: e.target.value })} />
                  </td>
                  <td>
                    <button className="btn btn--danger btn--sm"
                            onClick={() => delRow(i)} disabled={rows.length === 1}>
                      <Trash2 size={12} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button className="btn btn--ghost btn--sm" onClick={addRow}>
            <Plus size={13} /> Dodaj wiersz
          </button>

          <div className="form-group" style={{ marginTop: 16 }}>
            <label className="form-label" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <ClipboardPaste size={14} /> …albo wklej listę hurtem
            </label>
            <textarea className="form-control"
                      style={{ minHeight: 90, fontFamily: 'var(--font-mono)', fontSize: 12 }}
                      value={bulk} onChange={e => setBulk(e.target.value)}
                      placeholder={[
                        '001 Wyciągi bankowe',
                        '002 Faktury zakupu | tylko podgląd',
                      ].join('\n')} />
            <div style={{
              display: 'flex', alignItems: 'center', gap: 8, marginTop: 6, flexWrap: 'wrap',
            }}>
              <button className="btn btn--ghost btn--sm" onClick={applyBulk} disabled={!bulk.trim()}>
                Dopisz do listy
              </button>
              <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                Jedno uprawnienie w wierszu. Po znaku „|" możesz dopisać opis.
              </span>
            </div>
          </div>
        </div>

        <div className="modal__footer" style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button className="btn btn--ghost btn--sm" onClick={onClose} disabled={busy}>
            Anuluj
          </button>
          <button className="btn btn--primary btn--sm" onClick={save} disabled={busy}>
            <Check size={13} /> {busy
              ? 'Zapisuję…'
              : isExisting
                ? `Dopisz do grupy (${ready.length})`
                : `Utwórz grupę (${ready.length})`}
          </button>
        </div>
      </div>
    </div>
  )
}
