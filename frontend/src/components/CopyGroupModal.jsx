import { useEffect, useState } from 'react'
import { X, Check, Copy } from 'lucide-react'
import { listSystems, listPermissions, copyPermissionGroup } from '../api'
import { groupPerms } from './ItemFields'

/**
 * Kopiowanie JEDNEJ grupy uprawnień z innego programu do bieżącego.
 *
 * Pozwala raz zdefiniowaną grupę (np. „Rejestry księgowe") użyć w kolejnych
 * programach bez wpisywania od nowa. Wybierasz program źródłowy, jego grupę,
 * ewentualnie zmieniasz nazwę docelową. Pozycje już obecne w grupie docelowej
 * (po nazwie) są pomijane.
 */
export default function CopyGroupModal({ system, existingGroups = [], onClose, onDone }) {
  const [systems, setSystems]   = useState([])
  const [sourceId, setSourceId] = useState('')
  const [srcGroups, setSrcGroups] = useState([])   // [{ group, count }]
  const [group, setGroup]       = useState('')
  const [targetName, setTargetName] = useState('')
  const [loadingGroups, setLoadingGroups] = useState(false)
  const [busy, setBusy]         = useState(false)
  const [err, setErr]           = useState(null)

  // Programy do wyboru: z listą uprawnień, poza bieżącym i „tylko dostęp".
  useEffect(() => {
    listSystems().then(r => {
      setSystems((r.data || []).filter(
        s => s.id !== system.id && !s.access_only && s.permission_count > 0))
    }).catch(() => setSystems([]))
  }, [system.id])

  // Po wyborze źródła — pobierz jego grupy (z licznikami pozycji).
  useEffect(() => {
    if (!sourceId) { setSrcGroups([]); setGroup(''); return }
    setLoadingGroups(true); setErr(null)
    listPermissions(Number(sourceId))
      .then(r => {
        const own = (r.data || []).filter(p => !p.is_admin_option && !p.is_access_only)
        const groups = groupPerms(own)
          .filter(g => g.group)                       // tylko nazwane grupy
          .map(g => ({ group: g.group, count: g.items.length }))
        setSrcGroups(groups)
        setGroup(groups[0]?.group || '')
      })
      .catch(() => setSrcGroups([]))
      .finally(() => setLoadingGroups(false))
  }, [sourceId])

  const chosen = srcGroups.find(g => g.group === group)

  async function save() {
    if (!sourceId) { setErr('Wybierz program źródłowy.'); return }
    if (!group)    { setErr('Wybierz grupę do skopiowania.'); return }
    setBusy(true); setErr(null)
    try {
      const r = await copyPermissionGroup(system.id, {
        source_system_id: Number(sourceId),
        group_name: group,
        target_group_name: targetName.trim() || null,
      })
      const { copied, skipped, group_name } = r.data
      if (copied === 0) {
        setErr(`Nie skopiowano nic — wszystkie pozycje grupy „${group_name}" już są `
               + `w tym programie (pominięto ${skipped}).`)
        setBusy(false)
        return
      }
      onDone()
    } catch (ex) {
      setErr(ex.response?.data?.detail || 'Nie udało się skopiować grupy')
      setBusy(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth: 620, width: '92vw' }}>
        <div className="modal__header">
          <div>
            <Copy size={16} style={{ verticalAlign: 'middle', marginRight: 6 }} />
            Kopiuj grupę uprawnień → {system.name}
          </div>
          <button className="btn btn--ghost btn--sm" onClick={onClose}><X size={14} /></button>
        </div>

        <div className="modal__body">
          {err && <div className="alert alert--error mb-4">{err}</div>}

          <div className="form-group">
            <label className="form-label">Program źródłowy *</label>
            <select className="form-control" value={sourceId}
                    onChange={e => setSourceId(e.target.value)}>
              <option value="">— wybierz program —</option>
              {systems.map(s => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
            {systems.length === 0 && (
              <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 4 }}>
                Brak innych programów z listą uprawnień.
              </div>
            )}
          </div>

          <div className="form-group">
            <label className="form-label">Grupa do skopiowania *</label>
            <select className="form-control" value={group} disabled={!sourceId || loadingGroups}
                    onChange={e => setGroup(e.target.value)}>
              {loadingGroups && <option value="">Ładowanie…</option>}
              {!loadingGroups && srcGroups.length === 0 && (
                <option value="">{sourceId ? 'Ten program nie ma nazwanych grup' : '—'}</option>
              )}
              {srcGroups.map(g => (
                <option key={g.group} value={g.group}>{g.group} ({g.count})</option>
              ))}
            </select>
          </div>

          <div className="form-group">
            <label className="form-label">Nazwa grupy w tym programie</label>
            <input className="form-control" list="szup-copy-target-groups"
                   value={targetName} onChange={e => setTargetName(e.target.value)}
                   placeholder={group || 'domyślnie ta sama co źródłowa'} />
            <datalist id="szup-copy-target-groups">
              {existingGroups.map(g => <option key={g} value={g} />)}
            </datalist>
            <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 4 }}>
              Puste = ta sama nazwa co źródłowa. Jeśli podasz nazwę istniejącej grupy,
              pozycje zostaną do niej dopisane (bez duplikatów).
            </div>
          </div>
        </div>

        <div className="modal__footer" style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button className="btn btn--ghost btn--sm" onClick={onClose} disabled={busy}>Anuluj</button>
          <button className="btn btn--primary btn--sm" onClick={save}
                  disabled={busy || !sourceId || !group}>
            <Check size={13} /> {busy
              ? 'Kopiuję…'
              : `Skopiuj grupę${chosen ? ` (${chosen.count})` : ''}`}
          </button>
        </div>
      </div>
    </div>
  )
}
