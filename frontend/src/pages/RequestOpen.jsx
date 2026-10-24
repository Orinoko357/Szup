import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { getRequest, errorMessage } from '../api'
import { RequestModal } from './Manager'
import { LoadError } from '../components/ui/LoadState'

/**
 * /requests/view/:id — pojedynczy wniosek otwierany z pulpitu przez
 * superadmina (konto awaryjne nie ma strony „Wnioski”). Widok tylko do
 * odczytu; akcje (zatwierdź / odrzuć) pokazują się wyłącznie tam, gdzie
 * backend zwraca `can_act` — np. akceptacja wyższa wniosku „dla siebie”
 * kierownika, nad którym nie ma nikogo w strukturze (rezerwa superadmina).
 * Ten sam widok co u kierownika (RequestModal z Manager.jsx).
 */
export default function RequestOpen() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [req, setReq]         = useState(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr]         = useState(null)

  async function load() {
    setLoading(true); setErr(null)
    try { setReq((await getRequest(id)).data) }
    catch (ex) { setErr(errorMessage(ex, `Nie udało się wczytać wniosku #${id}`)) }
    finally { setLoading(false) }
  }
  useEffect(() => { load() }, [id])

  // Po akcji/powrocie — pulpit; fokus na jego h1 ustawia RouteFocus (App.jsx).
  const back = () => navigate('/')

  if (loading && !req) {
    return <div style={{ color: 'var(--color-text-muted)', padding: 18 }}>Ładowanie wniosku…</div>
  }
  if (err && !req) {
    return (
      <div>
        <div className="page-header">
          <div>
            <h1 className="page-header__title">Wniosek #{id}</h1>
            <div className="page-header__sub">Podgląd wniosku</div>
          </div>
          <button type="button" className="btn btn--ghost" onClick={back}>← Wróć do pulpitu</button>
        </div>
        <LoadError message={err} onRetry={load} busy={loading} />
      </div>
    )
  }
  if (!req) return null
  // key z can_act — po zmianie uprawnień do kroku widok montuje się od nowa.
  return (
    <>
      {/* v3.11 (N3): dlaczego superadmin widzi ten wniosek / czemu nie może działać. */}
      {!req.can_act && req.waiting_for && !['completed', 'rejected'].includes(req.status) && (
        <div role="note" className="alert alert--info" style={{ fontSize: 13, marginBottom: 12 }}>
          Wniosek czeka na: <strong>{req.waiting_for}</strong>. Superadmin może działać tylko awaryjnie —
          gdy w strukturze nie ma nikogo uprawnionego do bieżącego kroku; tu możesz go tylko podejrzeć.
        </div>
      )}
      <RequestModal key={`${req.id}:${req.can_act ? 1 : 0}`} request={req}
                    backLabel="← Wróć do pulpitu"
                    onClose={back}
                    onDone={back}
                    onRefresh={(upd) => { if (upd) setReq(upd); else load() }} />
    </>
  )
}
