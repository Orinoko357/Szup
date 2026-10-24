/**
 * Zakładki (wzorzec WAI-ARIA „tabs”): strzałki lewo/prawo, Home/End
 * przechodzą między zakładkami i od razu je aktywują. Podpinane jako
 * onKeyDown elementu role="tablist" (Wnioski, Moi pracownicy, Rejestr).
 */
export function onTablistKeyDown(e) {
  const tabs = Array.from(e.currentTarget.querySelectorAll('[role="tab"]'))
  const i = tabs.indexOf(e.target)
  if (i < 0) return
  const next = e.key === 'ArrowRight' ? (i + 1) % tabs.length
    : e.key === 'ArrowLeft' ? (i - 1 + tabs.length) % tabs.length
    : e.key === 'Home' ? 0
    : e.key === 'End' ? tabs.length - 1
    : null
  if (next == null) return
  e.preventDefault()
  tabs[next].focus()
  tabs[next].click()
}
