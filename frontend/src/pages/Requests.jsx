import { useEffect, useState } from 'react'
import { onTablistKeyDown } from '../components/ui/tabs'
import { useSearchParams } from 'react-router-dom'
import Manager from './Manager'
import { RequestsTab } from './ItRequestsTab'
import NameChangeQueue from '../components/NameChangeQueue'
import { workflowDashboard, errorMessage } from '../api'
import { toast } from '../components/ui/feedback'
import { workRoles, hasAnyRole } from '../roles'

/**
 * v3.0 — jedna strona „Wnioski” zamiast osobnych „Wnioski” (kierownik)
 * i „Do realizacji” (IT). Zakładki zależą od pełnionych funkcji; każda
 * zakładka to dotychczasowy widok (ta sama logika), osadzony bez własnego
 * nagłówka. Parametry: ?tab=handle|mine|it|names, ?open=<id wniosku>.
 */
const TABS = [
  { id: 'handle', label: 'Do obsługi',      roles: ['manager'],
    sub: 'Do zrobienia: wybór uprawnień dla pracowników i akceptacje (w tym akceptacja wyższa)' },
  { id: 'mine',   label: 'Moje wnioski',    roles: ['manager'],
    sub: 'Wnioski, które złożyłeś(aś) — bieżący status i etap obiegu' },
  { id: 'it',     label: 'Realizacja IT',   roles: ['it_staff'],
    sub: 'Realizacja wniosków o uprawnienia' },
  { id: 'names',  label: 'Zmiany nazwiska', roles: ['it_staff'],
    sub: 'Zgłoszenia zmiany nazwiska do realizacji przez IT' },
]


export default function Requests() {
  // Zakładki operacyjne (w tym kolejka zmian nazwiska — tylko IT); admin
  // i superadmin bez roli IT ich nie widzą.
  const roles = workRoles()
  const tabs = TABS.filter(t => hasAnyRole(roles, t.roles))
  const [params, setParams] = useSearchParams()
  const wanted = params.get('tab')
  const tab = tabs.some(t => t.id === wanted) ? wanted : tabs[0]?.id
  // ?open= odczytujemy raz i usuwamy z adresu, żeby odświeżenie nie otwierało ponownie.
  // Trafia WYŁĄCZNIE do zakładki z adresu (open.tab) i jest czyszczony po użyciu
  // oraz przy zmianie zakładki — wcześniej ten sam wniosek otwierał się ponownie
  // (także w złym widoku) po przełączeniu zakładki.
  // Reagujemy także na ZMIANĘ ?open= po zamontowaniu (wyszukiwarka Ctrl+K
  // nawiguje, gdy jesteśmy już na /requests). `nonce` przemontowuje osadzony
  // widok, żeby jego jednorazowa obsługa „open” zadziałała dla nowego numeru.
  const [open, setOpen] = useState({ id: null, tab: null, nonce: 0 })
  const consumeOpen = () => setOpen(o => ({ ...o, id: null }))
  const urlOpen = params.get('open')
  useEffect(() => {
    if (!urlOpen) return
    setOpen(o => ({ id: urlOpen, tab, nonce: o.nonce + 1 }))
    const p = new URLSearchParams(params); p.delete('open')
    setParams(p, { replace: true })
  }, [urlOpen])
  const openFor = (t) => (open.id && open.tab === t ? open.id : null)

  const [fullView, setFullView] = useState(false)
  const [counts, setCounts] = useState({})
  function loadCounts() {
    workflowDashboard().then(r => {
      const d = r.data || {}
      setCounts({
        handle: (d.pending_prepare_count || 0) + (d.pending_approve_count || 0),
        it: d.pending_execute_count || 0,
        names: d.pending_names_count || 0,
      })
    }).catch(ex => toast(errorMessage(ex, 'Nie udało się pobrać liczników zakładek'), { tone: 'warning' }))
  }
  useEffect(() => { loadCounts() }, [])

  const current = tabs.find(t => t.id === tab)
  const pick = (id) => { setFullView(false); consumeOpen(); setParams({ tab: id }) }

  // Nagłówek i zakładki ukrywane warunkowo (nie wczesnym return), żeby osadzone
  // widoki nie były przemontowywane i nie gubiły otwartego wniosku.
  return (
    <div>
      {!fullView && (
        <div className="page-header">
          <div>
            <h1 className="page-header__title">Wnioski</h1>
            <div className="page-header__sub">{current?.sub}</div>
          </div>
        </div>
      )}
      {!fullView && tabs.length > 1 && (
        <div className="tabs" role="tablist" aria-label="Rodzaj wniosków" style={{ marginTop: 0 }}
             onKeyDown={onTablistKeyDown}>
          {tabs.map(t => (
            <button key={t.id} role="tab" aria-selected={t.id === tab} tabIndex={t.id === tab ? 0 : -1}
                    id={`requests-tab-${t.id}`} aria-controls="requests-panel"
                    className={`tab-btn${t.id === tab ? ' active' : ''}`} onClick={() => pick(t.id)}>
              {t.label}
              {counts[t.id] > 0 && <span className="tab-count">{counts[t.id]}</span>}
            </button>
          ))}
        </div>
      )}
      {/* Panel zakładki (role=tabpanel tylko, gdy jest pasek zakładek). */}
      <div {...(!fullView && tabs.length > 1
        ? { role: 'tabpanel', id: 'requests-panel', 'aria-labelledby': `requests-tab-${tab}` } : {})}>
      {(tab === 'handle' || tab === 'mine') && (
        <Manager key={`m-${open.nonce}`} view={tab} openId={openFor(tab)} onOpenConsumed={consumeOpen}
                 onViewChange={setFullView} onChanged={loadCounts} />
      )}
      {tab === 'it' && (
        <RequestsTab key={`it-${open.nonce}`} openId={openFor('it')} onOpenConsumed={consumeOpen}
                     onViewChange={setFullView} onChanged={loadCounts} />
      )}
      {tab === 'names' && <NameChangeQueue onChanged={loadCounts} />}
      </div>
    </div>
  )
}
