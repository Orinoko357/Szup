import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import Manager from './Manager'
import { RequestsTab } from './IT'
import NameChangeQueue from '../components/NameChangeQueue'
import { workflowDashboard } from '../api'
import { getUserRoles, hasAnyRole } from '../roles'

/**
 * v3.0 — jedna strona „Wnioski” zamiast osobnych „Wnioski” (kierownik)
 * i „Do realizacji” (IT). Zakładki zależą od pełnionych funkcji; każda
 * zakładka to dotychczasowy widok (ta sama logika), osadzony bez własnego
 * nagłówka. Parametry: ?tab=handle|mine|it|names, ?open=<id wniosku>.
 */
const TABS = [
  { id: 'handle', label: 'Do obsługi',      roles: ['manager'],
    sub: 'Do zrobienia: wybór uprawnień dla pracowników i akceptacje (w tym wyższego rzędu)' },
  { id: 'mine',   label: 'Moje wnioski',    roles: ['manager'],
    sub: 'Wnioski, które złożyłeś(aś) — bieżący status i etap obiegu' },
  { id: 'it',     label: 'Realizacja IT',   roles: ['it_staff'],
    sub: 'Realizacja wniosków o uprawnienia' },
  { id: 'names',  label: 'Zmiany nazwiska', roles: ['it_staff'],
    sub: 'Zgłoszenia zmiany nazwiska do realizacji przez IT' },
]

export default function Requests() {
  const roles = getUserRoles()
  const tabs = TABS.filter(t => hasAnyRole(roles, t.roles))
  const [params, setParams] = useSearchParams()
  const wanted = params.get('tab')
  const tab = tabs.some(t => t.id === wanted) ? wanted : tabs[0]?.id
  // ?open= odczytujemy raz i usuwamy z adresu, żeby odświeżenie nie otwierało ponownie.
  // Trafia WYŁĄCZNIE do zakładki z adresu (openTab) i jest czyszczony po użyciu
  // oraz przy zmianie zakładki — wcześniej ten sam wniosek otwierał się ponownie
  // (także w złym widoku) po przełączeniu zakładki.
  const [openId, setOpenId] = useState(() => params.get('open'))
  const [openTab] = useState(() => tab)
  const consumeOpen = () => setOpenId(null)
  useEffect(() => {
    if (params.get('open')) {
      const p = new URLSearchParams(params); p.delete('open')
      setParams(p, { replace: true })
    }
  }, [])

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
    }).catch(() => {})
  }
  useEffect(() => { loadCounts() }, [])

  const current = tabs.find(t => t.id === tab)
  const pick = (id) => { setFullView(false); setOpenId(null); setParams({ tab: id }) }

  // Nagłówek i zakładki ukrywane warunkowo (nie wczesnym return), żeby osadzone
  // widoki nie były przemontowywane i nie gubiły otwartego wniosku.
  return (
    <div>
      {!fullView && (
        <div className="page-header">
          <div>
            <div className="page-header__title">Wnioski</div>
            <div className="page-header__sub">{current?.sub}</div>
          </div>
        </div>
      )}
      {!fullView && tabs.length > 1 && (
        <div className="tabs" role="tablist" style={{ marginTop: 0 }}>
          {tabs.map(t => (
            <button key={t.id} role="tab" aria-selected={t.id === tab}
                    className={`tab-btn${t.id === tab ? ' active' : ''}`} onClick={() => pick(t.id)}>
              {t.label}
              {counts[t.id] > 0 && <span className="tab-count">{counts[t.id]}</span>}
            </button>
          ))}
        </div>
      )}
      {(tab === 'handle' || tab === 'mine') && (
        <Manager view={tab} openId={tab === openTab ? openId : null} onOpenConsumed={consumeOpen}
                 onViewChange={setFullView} onChanged={loadCounts} />
      )}
      {tab === 'it' && (
        <RequestsTab openId={tab === openTab ? openId : null} onOpenConsumed={consumeOpen}
                     onViewChange={setFullView} onChanged={loadCounts} />
      )}
      {tab === 'names' && <NameChangeQueue onChanged={loadCounts} />}
    </div>
  )
}
