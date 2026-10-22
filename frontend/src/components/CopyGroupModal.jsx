import { useEffect, useState } from 'react'
import { Check } from 'lucide-react'
import { listSystems, listPermissions, copyPermissionGroup, errorMessage } from '../api'
import { groupPerms } from './ItemFields'
import Modal from './ui/Modal'
import Field from './ui/Field'
import { toast } from './ui/feedback'

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
    }).catch(ex => {
      setSystems([])
      toast(errorMessage(ex, 'Nie udało się pobrać listy programów'), { tone: 'warning' })
    })
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
      .catch(ex => {
        setSrcGroups([])
        toast(errorMessage(ex, 'Nie udało się pobrać grup programu źródłowego'), { tone: 'warning' })
      })
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
      setErr(errorMessage(ex, 'Nie udało się skopiować grupy'))
      setBusy(false)
    }
  }

  // Wspólne ui/Modal; etykiety powiązane z polami przez ui/Field.
  return (
    <Modal title={`Kopiuj grupę uprawnień do programu ${system.name}`} onClose={onClose} width={620}
           footer={<>
             <button type="button" className="btn btn--ghost btn--sm" onClick={onClose} disabled={busy}>Anuluj</button>
             <button type="button" className="btn btn--primary btn--sm" onClick={save}
                     disabled={busy || !sourceId || !group}>
               <Check size={13} aria-hidden="true" /> {busy
                 ? 'Kopiuję…'
                 : `Skopiuj grupę${chosen ? ` (${chosen.count})` : ''}`}
             </button>
           </>}>
      {err && <div className="alert alert--error mb-4" role="alert">{err}</div>}

      <Field label="Program źródłowy" required
             hint={systems.length === 0 ? 'Brak innych programów z listą uprawnień.' : null}>
        <select className="form-control" value={sourceId} data-autofocus
                onChange={e => setSourceId(e.target.value)}>
          <option value="">— wybierz program —</option>
          {systems.map(s => (
            <option key={s.id} value={s.id}>{s.name}</option>
          ))}
        </select>
      </Field>

      <Field label="Grupa do skopiowania" required>
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
      </Field>

      <Field label="Nazwa grupy w tym programie"
             hint="Puste = ta sama nazwa co źródłowa. Jeśli podasz nazwę istniejącej grupy, pozycje zostaną do niej dopisane (bez duplikatów).">
        <input className="form-control" list="szup-copy-target-groups"
               value={targetName} onChange={e => setTargetName(e.target.value)}
               placeholder={group || 'domyślnie ta sama co źródłowa'} />
      </Field>
      <datalist id="szup-copy-target-groups">
        {existingGroups.map(g => <option key={g} value={g} />)}
      </datalist>
    </Modal>
  )
}
