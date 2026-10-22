import { useEffect, useState } from 'react'
import {
  GitBranch, Plus, Save, X, Trash2, RefreshCw, LayoutList,
  ChevronUp, ChevronDown, AlertTriangle,
} from 'lucide-react'
import {
  listWorkflowTemplates, createWorkflowTemplate, updateWorkflowTemplate,
  deleteWorkflowTemplate, getWorkflowTemplate,
 errorMessage} from '../api'
import { fmtDateTime } from '../serverTime'
import { toast, ask } from '../components/ui/feedback'
import Field from '../components/ui/Field'
import { NODE_LABEL } from '../labels'


/**
 * Liniowy edytor obiegu wniosków.
 *
 * Silnik obiegu jest liniowy — każdy krok ma dokładnie jedno wyjście do
 * następnego. Zamiast rysować strzałki (React Flow) admin układa kroki
 * w kolejności (góra→dół); połączenia tworzą się automatycznie. „Zgłoszenie"
 * (start) jest zawsze pierwsze, „Zakończenie" (end) zawsze ostatnie.
 */

// Kolor akcentu kafelka (lewy pasek) — tokeny design systemu WODS.
const NODE_ACCENT = {
  start: 'var(--color-success)',
  select_permissions: 'var(--color-warning)',
  manager_approve: 'var(--color-info)',
  higher_manager_approve: 'var(--color-gold-dark)',
  it_execute: 'var(--color-selected)',
  end: 'var(--color-text-muted)',
}

// Katalog kroków możliwych do wstawienia w środku obiegu (bez start/end).
const STEP_CATALOG = [
  {
    type: 'select_permissions',
    label: NODE_LABEL.select_permissions,
    hint: 'Kierownik referatu/biura wybiera systemy i uprawnienia dla pracownika — wybór jest jednocześnie zatwierdzeniem.',
  },
  {
    type: 'higher_manager_approve',
    label: NODE_LABEL.higher_manager_approve,
    hint: 'Kierownik nadrzędny (kierownik komórki nadrzędnej). Pomijany automatycznie, gdy komórka nie ma flagi „wymaga akceptacji wyższego rzędu".',
  },
  {
    type: 'it_execute',
    label: NODE_LABEL.it_execute,
    hint: 'Pracownik Biura Informatyki realizuje wniosek technicznie i potwierdza wykonanie.',
  },
  {
    type: 'manager_approve',
    label: `${NODE_LABEL.manager_approve} (opcjonalna)`,
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
// Zwraca listę kroków albo null, gdy grafu nie da się bezpiecznie przedstawić
// jako listy (brak startu/końca, rozgałęzienia, węzły poza łańcuchem, pętle).
// Wtedy edytor NIE podstawia kroków domyślnych — zapis nadpisałby prawdziwy graf.
function linearizeGraph(graph) {
  const nodes = graph?.nodes
  const edges = graph?.edges
  if (!Array.isArray(nodes) || !Array.isArray(edges) || nodes.length < 2) return null
  const byId = Object.fromEntries(nodes.map(n => [n.id, n]))
  const nextOf = {}
  for (const e of edges) {
    if (e.from in nextOf && nextOf[e.from] !== e.to) return null   // rozgałęzienie
    nextOf[e.from] = e.to
  }

  const starts = nodes.filter(n => n.type === 'start')
  if (starts.length !== 1) return null
  const ordered = []
  let cur = starts[0]
  const seen = new Set()
  while (cur) {
    if (seen.has(cur.id)) return null                                 // pętla
    seen.add(cur.id)
    ordered.push(cur)
    cur = byId[nextOf[cur.id]]
  }
  if (ordered.length !== nodes.length) return null                    // węzły poza łańcuchem
  if (ordered[ordered.length - 1].type !== 'end') return null
  return ordered.map(n => ({ type: n.type, label: n.label || n.type, props: n.props || {} }))
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
    } catch (ex) { setErr(errorMessage(ex, 'Błąd ładowania')) }
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
          <h1 className="page-header__title">Szablony obiegu</h1>
          <div className="page-header__sub">
            Ułóż kroki obiegu w kolejności — połączenia tworzą się automatycznie
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn btn--ghost" onClick={load} disabled={loading}>
            <RefreshCw size={14} /> Odśwież
          </button>
          <button className="btn btn--action" onClick={() => setEditing({ mode: 'add' })}>
            <Plus size={14} /> Nowy szablon
          </button>
        </div>
      </div>

      {err && <div className="alert alert--error mb-4">{err}</div>}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        {loading && <div className="card" style={{ color: 'var(--color-text-muted)' }}>Ładowanie…</div>}
        {!loading && items.length === 0 && (
          <div className="card" style={{ color: 'var(--color-text-muted)', padding: 16 }}>
            <GitBranch size={14} style={{ verticalAlign: 'middle', marginRight: 6 }} />
            Brak szablonów. Utwórz pierwszy przyciskiem „Nowy szablon” — bez szablonu obiegu nie da się dodać typu wniosku.
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
    if (!await ask(`Usunąć szablon "${tpl.name}"?`, { title: 'Potwierdź operację', confirmLabel: 'Usuń szablon', danger: true })) return
    try { await deleteWorkflowTemplate(tpl.id); onReload(); toast(`Usunięto szablon „${tpl.name}”`) }
    catch (ex) { toast(errorMessage(ex, 'Błąd'), { tone: 'error' }) }
  }
  return (
    <section className="card" style={{ padding: '18px 20px', opacity: tpl.is_active ? 1 : 0.8 }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-start', gap: 12 }}>
        <div style={{ flex: '1 1 360px', minWidth: 0 }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8 }}>
            <h2 style={{ margin: 0, fontSize: 17, fontWeight: 800, color: 'var(--color-heading)' }}>{tpl.name}</h2>
            <span style={{ padding: '1px 8px', borderRadius: 10, background: 'var(--color-neutral-bg)',
                           color: 'var(--color-neutral-text)', fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 700 }}>
              v{tpl.version}
            </span>
            {!tpl.is_active && <span className="badge badge--neutral">nieaktywny</span>}
          </div>
          {tpl.description && (
            <p style={{ margin: '4px 0 0', fontSize: 14, color: 'var(--color-text)' }}>{tpl.description}</p>
          )}
          <p style={{ margin: '4px 0 0', fontSize: 12, color: 'var(--color-text-muted)' }}>
            Używany przez {tpl.used_by_request_types_count} typów wniosków ·{' '}
            {tpl.active_instances_count} aktywnych instancji ·{' '}
            utworzony {fmtDateTime(tpl.created_at)}
            {tpl.created_by_name && ` przez ${tpl.created_by_name}`}
          </p>
        </div>
        <button className="btn btn--action" onClick={onEdit}>
          <LayoutList size={14} /> Otwórz w edytorze
        </button>
        <button className="btn btn--ghost" onClick={del} aria-label="Usuń szablon" title="Usuń szablon"
                style={{ color: 'var(--color-error-text)' }}><Trash2 size={15} /></button>
      </div>

      {graph && graph.nodes && (
        <ol aria-label="Kroki obiegu" style={{ listStyle: 'none', margin: '14px 0 0', padding: 12,
                                               background: 'var(--bg-secondary)', borderRadius: 8,
                                               display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 6 }}>
          {graph.nodes.map((n, idx) => (
            <li key={n.id} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '5px 10px',
                             borderRadius: 6, background: 'var(--color-card)', border: '1px solid var(--color-border)',
                             fontSize: 13, fontWeight: 600 }}>
                <span aria-hidden="true" style={{ width: 8, height: 8, borderRadius: '50%',
                                                  background: NODE_ACCENT[n.type] || 'var(--color-text-muted)' }} />
                {n.label || n.type}
              </span>
              {idx < graph.nodes.length - 1 && (
                <span aria-hidden="true" style={{ color: 'var(--color-text-muted)' }}>→</span>
              )}
            </li>
          ))}
        </ol>
      )}
    </section>
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
  // Błąd wczytania szablonu — blokuje zapis (nie nadpisujemy grafu, którego nie znamy).
  const [loadErr, setLoadErr] = useState(null)

  useEffect(() => {
    if (isEdit && templateId) {
      getWorkflowTemplate(templateId).then(r => {
        setMeta({
          name: r.data.name, description: r.data.description || '',
          is_active: r.data.is_active, version: r.data.version,
          created_by_name: r.data.created_by_name,
        })
        let lin = null
        try { lin = linearizeGraph(JSON.parse(r.data.graph_json)) } catch { lin = null }
        const steps = lin && lin.filter(s => s.type !== 'start' && s.type !== 'end')
        if (steps && steps.length) {
          setMiddle(steps)
        } else {
          // Nie podstawiamy kroków domyślnych — zapis zniszczyłby istniejący obieg.
          setMiddle([])
          setLoadErr('Grafu tego szablonu nie da się przedstawić jako listy kroków (uszkodzony lub nieliniowy graph_json). Edycja i zapis są zablokowane.')
        }
        setLoading(false)
      }).catch(ex => {
        setLoadErr(errorMessage(ex, 'Nie udało się wczytać szablonu. Edycja i zapis są zablokowane.'))
        setLoading(false)
      })
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
    if (loadErr) return
    if (!meta.name.trim()) { setErr('Podaj nazwę szablonu'); return }
    if (middle.length === 0) { setErr('Dodaj przynajmniej jeden krok między zgłoszeniem a zakończeniem'); return }
    if (!middle.some(s => s.type === 'it_execute')) {
      if (!await ask('Obieg nie ma kroku „Realizacja IT" — wniosek zakończy się bez realizacji technicznej. Zapisać mimo to?', { title: 'Brak kroku IT', confirmLabel: 'Zapisz mimo to' })) return
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
      setErr(errorMessage(ex, 'Błąd zapisu'))
    } finally { setSaving(false) }
  }

  if (loading) {
    return <div className="card" style={{ color: 'var(--color-text-muted)' }}>Ładowanie szablonu…</div>
  }

  if (loadErr) {
    return (
      <div>
        <div className="page-header">
          <div>
            <h1 className="page-header__title">Edycja: {meta.name || 'szablon'}</h1>
          </div>
          <button className="btn btn--ghost" onClick={onCancel}>
            <X size={14} /> Wróć do listy
          </button>
        </div>
        <div className="alert alert--error" role="alert" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <AlertTriangle size={14} /> {loadErr}
        </div>
      </div>
    )
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-header__title">
            {isEdit ? `Edycja: ${meta.name || 'szablon'}` : 'Nowy szablon obiegu'}
          </h1>
          <div className="page-header__sub">
            Kroki wykonują się po kolei z góry na dół. Zgłoszenie i zakończenie są stałe.
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn btn--ghost" onClick={onCancel}>
            <X size={14} /> Anuluj
          </button>
          <button className="btn btn--action" onClick={save} disabled={saving}>
            <Save size={14} /> {saving ? 'Zapis…' : 'Zapisz'}
          </button>
        </div>
      </div>

      {err && (
        <div className="alert alert--error mb-4" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <AlertTriangle size={14} /> {err}
        </div>
      )}

      {/* Metadane */}
      <section aria-label="Dane szablonu" className="card" style={{ padding: '18px 20px', marginBottom: 18, display: 'grid',
                                     gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 14 }}>
        <Field label="Nazwa" required>
          <input className="form-control" style={{ minHeight: 44 }} value={meta.name}
                 onChange={e => setMeta(m => ({ ...m, name: e.target.value }))} />
        </Field>
        <Field label="Opis">
          <input className="form-control" style={{ minHeight: 44 }} value={meta.description}
                 onChange={e => setMeta(m => ({ ...m, description: e.target.value }))} />
        </Field>
        <div className="form-group">
          <span className="form-label">Stan</span>
          <label className="form-check" style={{ minHeight: 44, fontSize: 14, color: 'var(--color-text)' }}>
            <input type="checkbox" checked={meta.is_active} style={{ width: 18, height: 18 }}
                   onChange={e => setMeta(m => ({ ...m, is_active: e.target.checked }))} />
            Aktywny — dostępny do wyboru
          </label>
        </div>
      </section>

      {/* Lista kroków */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 0, maxWidth: 760, margin: '0 auto' }}>
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
                <label className="form-check" style={{ fontSize: 13, marginTop: 6 }}>
                  <input type="checkbox" style={{ width: 18, height: 18 }}
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
      <div style={{ margin: '18px auto 0', maxWidth: 760, boxSizing: 'border-box', display: 'flex', gap: 10,
                    alignItems: 'center', flexWrap: 'wrap', padding: '14px 16px', background: 'var(--color-card)',
                    border: '1px dashed var(--color-input-border)', borderRadius: 10 }}>
        <label style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10, flex: '1 1 360px',
                        fontSize: 14, fontWeight: 700, color: 'var(--color-heading)' }}>
          Dodaj krok:
          <select className="form-control" style={{ minHeight: 44, flex: 1 }}
                  value={addType} onChange={e => setAddType(e.target.value)}>
            {STEP_CATALOG.map(s => <option key={s.type} value={s.type}>{s.label}</option>)}
          </select>
        </label>
        <button className="btn btn--ghost" onClick={addStep}>
          <Plus size={14} /> Dodaj na końcu
        </button>
      </div>
    </div>
  )
}

function StepTile({ fixed, type, index, label, sub, hint, editable, onLabel,
                    onUp, onDown, onRemove, extra }) {
  const accent = NODE_ACCENT[type] || 'var(--color-text-muted)'
  // v3.0: kolor kroku = pasek u góry kafla + kółko z numerem (bez lewej krawędzi).
  const ICONBTN = { width: 40, height: 40, padding: 0, display: 'grid', placeItems: 'center' }
  return (
    <div style={{
      background: fixed ? 'var(--bg-secondary)' : 'var(--color-card)',
      border: '1px solid var(--color-border)', borderRadius: 10, overflow: 'hidden',
    }}>
      <div style={{ height: 4, background: accent }} />
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-start', gap: 12, padding: '14px 16px' }}>
        <span aria-hidden="true" style={{
          flexShrink: 0, width: 30, height: 30, borderRadius: '50%', display: 'grid', placeItems: 'center',
          fontSize: 13, fontWeight: 800, color: '#fff', background: accent,
        }}>
          {fixed ? (type === 'start' ? 'S' : 'K') : index}
        </span>

        <div style={{ flex: '1 1 300px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '.08em',
                         textTransform: 'uppercase', color: 'var(--color-text-muted)' }}>
            {fixed ? (type === 'start' ? 'Start' : 'Koniec') : `Krok ${index}`}
          </span>
          {editable ? (
            <input className="form-control" aria-label="Nazwa kroku"
                   style={{ minHeight: 40, fontSize: 14, fontWeight: 700, color: 'var(--color-heading)' }}
                   value={label} onChange={e => onLabel(e.target.value)} />
          ) : (
            <strong style={{ fontSize: 15, color: 'var(--color-heading)' }}>{label}</strong>
          )}
          {(sub || hint) && (
            <span style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>{sub || hint}</span>
          )}
          {extra}
        </div>

        {!fixed && (
          <span style={{ display: 'flex', gap: 2, flex: 'none' }}>
            <button className="btn btn--ghost btn--sm" style={ICONBTN}
                    onClick={onUp} disabled={!onUp} title="W górę" aria-label="W górę"><ChevronUp size={15} /></button>
            <button className="btn btn--ghost btn--sm" style={ICONBTN}
                    onClick={onDown} disabled={!onDown} title="W dół" aria-label="W dół"><ChevronDown size={15} /></button>
            <button className="btn btn--ghost btn--sm" style={{ ...ICONBTN, color: 'var(--color-error-text)' }}
                    onClick={onRemove} title="Usuń krok" aria-label="Usuń krok"><Trash2 size={15} /></button>
          </span>
        )}
      </div>
    </div>
  )
}

function Arrow() {
  return (
    <div aria-hidden="true" style={{ display: 'flex', justifyContent: 'center', padding: '4px 0',
                                     color: 'var(--color-text-muted)' }}>
      <ChevronDown size={18} />
    </div>
  )
}


