import { useEffect, useState } from 'react'
import {
  GitBranch, Plus, Save, X, Trash2, RefreshCw, LayoutList,
  Play, ListChecks, UserCheck, Crown, Wrench, Flag,
  ChevronUp, ChevronDown, AlertTriangle,
} from 'lucide-react'
import {
  listWorkflowTemplates, createWorkflowTemplate, updateWorkflowTemplate,
  deleteWorkflowTemplate, getWorkflowTemplate,
} from '../api'
import { fmtDateTime } from '../serverTime'

/**
 * Liniowy edytor obiegu wniosków.
 *
 * Silnik obiegu jest liniowy — każdy krok ma dokładnie jedno wyjście do
 * następnego. Zamiast rysować strzałki (React Flow) admin układa kroki
 * w kolejności (góra→dół); połączenia tworzą się automatycznie. „Zgłoszenie"
 * (start) jest zawsze pierwsze, „Zakończenie" (end) zawsze ostatnie.
 */

const NODE_ICONS = {
  start: Play,
  select_permissions: ListChecks,
  manager_approve: UserCheck,
  higher_manager_approve: Crown,
  it_execute: Wrench,
  end: Flag,
}

// Kolor akcentu kafelka (lewy pasek) — tokeny design systemu WODS.
const NODE_ACCENT = {
  start: 'var(--color-success)',
  select_permissions: 'var(--color-warning)',
  manager_approve: 'var(--color-info)',
  higher_manager_approve: 'var(--color-gold-dark)',
  it_execute: 'var(--color-navy)',
  end: 'var(--color-text-muted)',
}

// Katalog kroków możliwych do wstawienia w środku obiegu (bez start/end).
const STEP_CATALOG = [
  {
    type: 'select_permissions',
    label: 'Wybór uprawnień i zatwierdzenie (kierownik)',
    hint: 'Kierownik referatu/biura wybiera systemy i uprawnienia dla pracownika — wybór jest jednocześnie zatwierdzeniem.',
  },
  {
    type: 'higher_manager_approve',
    label: 'Akceptacja kierownika wyższego rzędu',
    hint: 'Kierownik wydziału nadrzędnego. Pomijany automatycznie, gdy komórka nie ma flagi „wymaga akceptacji wyższego rzędu".',
  },
  {
    type: 'it_execute',
    label: 'Realizacja przez IT',
    hint: 'Pracownik Biura Informatyki realizuje wniosek technicznie i potwierdza wykonanie.',
  },
  {
    type: 'manager_approve',
    label: 'Osobna akceptacja kierownika (opcjonalna)',
    hint: 'Dodatkowy krok akceptacji przez kierownika — użyj tylko, gdy wybór uprawnień robi kto inny niż zatwierdzający.',
  },
]

const CATALOG_BY_TYPE = Object.fromEntries(STEP_CATALOG.map(s => [s.type, s]))

function labelFor(type, fallback) {
  return CATALOG_BY_TYPE[type]?.label || fallback || type
}

// Domyślny obieg — zgodny z opisem: HR zgłasza → kierownik wybiera uprawnienia
// (to zarazem zatwierdzenie) → (ew.) kierownik wyższego rzędu → realizacja IT → koniec.
// Bez podpisu papierowego.
const DEFAULT_MIDDLE = [
  { type: 'select_permissions',     label: labelFor('select_permissions'),     props: {} },
  { type: 'higher_manager_approve', label: labelFor('higher_manager_approve'),  props: { skip_if_not_required: true } },
  { type: 'it_execute',             label: labelFor('it_execute'),              props: {} },
]

// -----------------------------------------------------------------------
// Konwersja graph_json ↔ liniowa lista kroków
// -----------------------------------------------------------------------
function linearizeGraph(graph) {
  const nodes = graph?.nodes || []
  const edges = graph?.edges || []
  const byId = Object.fromEntries(nodes.map(n => [n.id, n]))
  const nextOf = {}
  for (const e of edges) if (!(e.from in nextOf)) nextOf[e.from] = e.to

  const startNode = nodes.find(n => n.type === 'start')
  const ordered = []
  if (startNode) {
    let cur = startNode
    const seen = new Set()
    while (cur && !seen.has(cur.id)) {
      seen.add(cur.id)
      ordered.push(cur)
      cur = byId[nextOf[cur.id]]
    }
  }
  // Fallback: gdy graf nieliniowy/uszkodzony — po prostu kolejność z tablicy.
  const list = ordered.length >= 2 ? ordered : nodes
  return list.map(n => ({ type: n.type, label: n.label || n.type, props: n.props || {} }))
}

function buildGraph(middle) {
  const steps = [
    { type: 'start', label: 'Zgłoszenie pracownika (HR)', props: {} },
    ...middle,
    { type: 'end', label: 'Zakończenie procesu', props: {} },
  ]
  const nodes = steps.map((s, i) => ({
    id: `n${i + 1}`, type: s.type, label: s.label,
    x: 40 + i * 200, y: 120, props: s.props || {},
  }))
  const edges = []
  for (let i = 0; i < nodes.length - 1; i++) {
    edges.push({ from: nodes[i].id, to: nodes[i + 1].id })
  }
  return { nodes, edges }
}

// =======================================================================
// Widok główny
// =======================================================================
export default function WorkflowTemplates() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)
  const [editing, setEditing] = useState(null)   // { mode:'add' } | { mode:'edit', id }

  async function load() {
    setLoading(true); setErr(null)
    try {
      const r = await listWorkflowTemplates({})
      setItems(r.data)
    } catch (ex) { setErr(ex.response?.data?.detail || 'Błąd ładowania') }
    finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  if (editing) {
    return (
      <LinearEditor
        mode={editing.mode}
        templateId={editing.id}
        onCancel={() => setEditing(null)}
        onSaved={() => { setEditing(null); load() }}
      />
    )
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-header__title">Szablony obiegu wniosków</div>
          <div className="page-header__sub">
            Ułóż kroki obiegu w kolejności — połączenia tworzą się automatycznie
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn btn--ghost btn--sm" onClick={load} disabled={loading}>
            <RefreshCw size={14} /> Odśwież
          </button>
          <button className="btn btn--action btn--sm" onClick={() => setEditing({ mode: 'add' })}>
            <Plus size={14} /> Nowy szablon
          </button>
        </div>
      </div>

      {err && <div className="alert alert--error mb-4">{err}</div>}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {loading && <div className="card" style={{ color: 'var(--color-text-muted)' }}>Ładowanie…</div>}
        {!loading && items.length === 0 && (
          <div className="card" style={{ color: 'var(--color-text-muted)', padding: 16 }}>
            <GitBranch size={14} style={{ verticalAlign: 'middle', marginRight: 6 }} />
            Brak szablonów. Zacznij od stworzenia pierwszego.
          </div>
        )}
        {items.map(t => (
          <TemplateCard key={t.id} tpl={t}
                        onEdit={() => setEditing({ mode: 'edit', id: t.id })}
                        onReload={load} />
        ))}
      </div>
    </div>
  )
}

function TemplateCard({ tpl, onEdit, onReload }) {
  let graph = null
  try { graph = JSON.parse(tpl.graph_json) } catch {}
  async function del() {
    if (!confirm(`Usunąć szablon "${tpl.name}"?`)) return
    try { await deleteWorkflowTemplate(tpl.id); onReload() }
    catch (ex) { alert(ex.response?.data?.detail || 'Błąd') }
  }
  return (
    <div className="card" style={{ padding: 12 }}>
      <div style={{ display: 'flex', alignItems: 'start', gap: 8 }}>
        <div style={{ flex: 1 }}>
          <strong style={{ fontSize: 14 }}>{tpl.name}</strong>
          <span style={{ fontSize: 11, color: 'var(--color-text-muted)', marginLeft: 8 }}>v{tpl.version}</span>
          {!tpl.is_active && (
            <span className="badge badge--neutral" style={{ fontSize: 10, marginLeft: 6 }}>nieaktywny</span>
          )}
          {tpl.description && (
            <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginTop: 4 }}>{tpl.description}</div>
          )}
          <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 4 }}>
            Używany przez {tpl.used_by_request_types_count} typów wniosków ·
            {tpl.active_instances_count} aktywnych instancji ·
            utworzony {fmtDateTime(tpl.created_at)}
            {tpl.created_by_name && ` przez ${tpl.created_by_name}`}
          </div>
        </div>
        <button className="btn btn--action btn--sm" onClick={onEdit}>
          <LayoutList size={12} /> Otwórz w edytorze
        </button>
        <button className="btn btn--ghost btn--sm" onClick={del}><Trash2 size={12} /></button>
      </div>

      {graph && graph.nodes && (
        <div style={{ marginTop: 10, padding: 10, background: 'var(--bg-secondary)', borderRadius: 6, overflowX: 'auto' }}>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', minWidth: 'max-content' }}>
            {graph.nodes.map((n, idx) => {
              const Icon = NODE_ICONS[n.type] || GitBranch
              return (
                <div key={n.id} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <div style={{
                    padding: '6px 10px', border: '1px solid var(--color-border)',
                    borderRadius: 4, background: 'var(--bg-primary)', minWidth: 120, textAlign: 'center',
                  }}>
                    <Icon size={12} style={{ verticalAlign: 'middle', color: 'var(--color-navy)', marginRight: 4 }} />
                    <span style={{ fontSize: 11, fontWeight: 600 }}>{n.label || n.type}</span>
                  </div>
                  {idx < graph.nodes.length - 1 && (
                    <span style={{ fontSize: 14, color: 'var(--color-text-muted)' }}>→</span>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

// =======================================================================
// Liniowy edytor kroków
// =======================================================================
function LinearEditor({ mode, templateId, onCancel, onSaved }) {
  const isEdit = mode === 'edit'
  const [meta, setMeta] = useState({
    name: '', description: '', is_active: true, version: 1, created_by_name: null,
  })
  const [middle, setMiddle] = useState(DEFAULT_MIDDLE)
  const [addType, setAddType] = useState('select_permissions')
  const [saving, setSaving] = useState(false)
  const [loading, setLoading] = useState(isEdit)
  const [err, setErr] = useState(null)

  useEffect(() => {
    if (isEdit && templateId) {
      getWorkflowTemplate(templateId).then(r => {
        setMeta({
          name: r.data.name, description: r.data.description || '',
          is_active: r.data.is_active, version: r.data.version,
          created_by_name: r.data.created_by_name,
        })
        try {
          const g = JSON.parse(r.data.graph_json)
          const lin = linearizeGraph(g).filter(s => s.type !== 'start' && s.type !== 'end')
          setMiddle(lin.length ? lin : DEFAULT_MIDDLE)
        } catch {
          setMiddle(DEFAULT_MIDDLE)
        }
        setLoading(false)
      }).catch(() => setLoading(false))
    }
  }, [isEdit, templateId])

  function move(i, dir) {
    setMiddle(m => {
      const j = i + dir
      if (j < 0 || j >= m.length) return m
      const copy = [...m]
      ;[copy[i], copy[j]] = [copy[j], copy[i]]
      return copy
    })
  }
  function removeAt(i) { setMiddle(m => m.filter((_, idx) => idx !== i)) }
  function setLabel(i, label) { setMiddle(m => m.map((s, idx) => idx === i ? { ...s, label } : s)) }
  function setProp(i, key, val) {
    setMiddle(m => m.map((s, idx) => idx === i ? { ...s, props: { ...(s.props || {}), [key]: val } } : s))
  }
  function addStep() {
    const cat = CATALOG_BY_TYPE[addType]
    const props = addType === 'higher_manager_approve' ? { skip_if_not_required: true } : {}
    setMiddle(m => [...m, { type: addType, label: cat.label, props }])
  }

  async function save() {
    setErr(null)
    if (!meta.name.trim()) { setErr('Podaj nazwę szablonu'); return }
    if (middle.length === 0) { setErr('Dodaj przynajmniej jeden krok między zgłoszeniem a zakończeniem'); return }
    if (!middle.some(s => s.type === 'it_execute')) {
      if (!confirm('Obieg nie ma kroku „Realizacja przez IT" — wniosek zakończy się bez realizacji technicznej. Zapisać mimo to?')) return
    }
    setSaving(true)
    try {
      const graph = buildGraph(middle)
      const payload = {
        name: meta.name.trim(),
        description: meta.description || null,
        graph_json: JSON.stringify(graph),
        is_active: meta.is_active,
      }
      if (isEdit) await updateWorkflowTemplate(templateId, payload)
      else await createWorkflowTemplate(payload)
      onSaved()
    } catch (ex) {
      setErr(ex.response?.data?.detail || ex.message || 'Błąd zapisu')
    } finally { setSaving(false) }
  }

  if (loading) {
    return <div className="card" style={{ color: 'var(--color-text-muted)' }}>Ładowanie szablonu…</div>
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-header__title">
            {isEdit ? `Edycja: ${meta.name || 'szablon'}` : 'Nowy szablon obiegu'}
          </div>
          <div className="page-header__sub">
            Kroki wykonują się po kolei z góry na dół. Zgłoszenie i zakończenie są stałe.
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn btn--action btn--sm" onClick={save} disabled={saving}>
            <Save size={14} /> {saving ? 'Zapis…' : 'Zapisz'}
          </button>
          <button className="btn btn--ghost btn--sm" onClick={onCancel}>
            <X size={14} /> Anuluj
          </button>
        </div>
      </div>

      {err && (
        <div className="alert alert--error mb-4" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <AlertTriangle size={14} /> {err}
        </div>
      )}

      {/* Metadane */}
      <div className="card" style={{ padding: 12, marginBottom: 12, display: 'grid',
                                     gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 8 }}>
        <Field label="Nazwa *">
          <input className="input input--sm" value={meta.name}
                 onChange={e => setMeta(m => ({ ...m, name: e.target.value }))} />
        </Field>
        <Field label="Opis">
          <input className="input input--sm" value={meta.description}
                 onChange={e => setMeta(m => ({ ...m, description: e.target.value }))} />
        </Field>
        <Field label="Stan">
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, paddingTop: 4 }}>
            <input type="checkbox" checked={meta.is_active}
                   onChange={e => setMeta(m => ({ ...m, is_active: e.target.checked }))} />
            Aktywny — dostępny do wyboru
          </label>
        </Field>
      </div>

      {/* Lista kroków */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxWidth: 720 }}>
        <StepTile fixed type="start" label="Zgłoszenie pracownika (HR)"
                  sub="Dział kadr zgłasza pracownika i wskazuje komórkę organizacyjną." />
        <Arrow />

        {middle.map((s, i) => (
          <div key={i}>
            <StepTile
              type={s.type}
              index={i + 1}
              label={s.label}
              editable
              onLabel={v => setLabel(i, v)}
              hint={CATALOG_BY_TYPE[s.type]?.hint}
              onUp={i > 0 ? () => move(i, -1) : null}
              onDown={i < middle.length - 1 ? () => move(i, +1) : null}
              onRemove={() => removeAt(i)}
              extra={s.type === 'higher_manager_approve' ? (
                <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, marginTop: 6 }}>
                  <input type="checkbox"
                         checked={!!s.props?.skip_if_not_required}
                         onChange={e => setProp(i, 'skip_if_not_required', e.target.checked)} />
                  Pomijaj, gdy komórka nie wymaga akceptacji wyższego rzędu
                </label>
              ) : null}
            />
            <Arrow />
          </div>
        ))}

        <StepTile fixed type="end" label="Zakończenie procesu"
                  sub={'Wniosek zrealizowany; uprawnienia widoczne w „Moje uprawnienia" pracownika.'} />
      </div>

      {/* Dodaj krok */}
      <div className="card" style={{ padding: 12, marginTop: 12, maxWidth: 720,
                                     display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-text-muted)' }}>Dodaj krok:</span>
        <select className="input input--sm" style={{ maxWidth: 340 }}
                value={addType} onChange={e => setAddType(e.target.value)}>
          {STEP_CATALOG.map(s => <option key={s.type} value={s.type}>{s.label}</option>)}
        </select>
        <button className="btn btn--ghost btn--sm" onClick={addStep}>
          <Plus size={12} /> Dodaj na końcu
        </button>
      </div>
    </div>
  )
}

function StepTile({ fixed, type, index, label, sub, hint, editable, onLabel,
                    onUp, onDown, onRemove, extra }) {
  const Icon = NODE_ICONS[type] || GitBranch
  const accent = NODE_ACCENT[type] || 'var(--color-text-muted)'
  return (
    <div className="card" style={{
      padding: 12, borderLeft: `3px solid ${accent}`,
      background: fixed ? 'var(--bg-secondary)' : 'var(--bg-primary)',
      display: 'flex', gap: 12, alignItems: 'flex-start',
    }}>
      <div style={{
        width: 34, height: 34, flex: 'none', borderRadius: 4,
        background: 'var(--bg-secondary)', display: 'grid', placeItems: 'center', color: accent,
      }}>
        <Icon size={17} />
      </div>

      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.5px',
                      textTransform: 'uppercase', color: 'var(--color-text-muted)' }}>
          {fixed ? (type === 'start' ? 'Start' : 'Koniec') : `Krok ${index}`}
        </div>
        {editable ? (
          <input className="input input--sm" style={{ marginTop: 4 }}
                 value={label} onChange={e => onLabel(e.target.value)} />
        ) : (
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--color-navy)', marginTop: 2 }}>{label}</div>
        )}
        {(sub || hint) && (
          <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 4 }}>{sub || hint}</div>
        )}
        {extra}
      </div>

      {!fixed && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2, flex: 'none' }}>
          <button className="btn btn--ghost btn--sm" style={{ padding: '2px 6px' }}
                  onClick={onUp} disabled={!onUp} title="W górę"><ChevronUp size={13} /></button>
          <button className="btn btn--ghost btn--sm" style={{ padding: '2px 6px' }}
                  onClick={onDown} disabled={!onDown} title="W dół"><ChevronDown size={13} /></button>
          <button className="btn btn--ghost btn--sm" style={{ padding: '2px 6px', color: 'var(--color-danger)' }}
                  onClick={onRemove} title="Usuń krok"><Trash2 size={13} /></button>
        </div>
      )}
    </div>
  )
}

function Arrow() {
  return (
    <div style={{ display: 'flex', justifyContent: 'center', color: 'var(--color-text-muted)' }}>
      <ChevronDown size={18} />
    </div>
  )
}

function Field({ label, children }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 3, fontSize: 11 }}>
      <span style={{ color: 'var(--color-text-muted)' }}>{label}</span>
      {children}
    </label>
  )
}
