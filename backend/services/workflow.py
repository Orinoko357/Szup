"""
Silnik obiegu wniosków (workflow engine).

Obieg jest opisany grafem węzłów (kafelków). Każdy węzeł ma typ z NODE_TYPES.
Krawędzie łączą węzły — silnik przechodzi po nich w kierunku „end".

Struktura graph_json (WorkflowTemplate.graph_json):

    {
      "nodes": [
        {"id":"n1", "type":"start",                  "label":"Zgłoszenie",         "props":{}},
        {"id":"n2", "type":"select_permissions",     "label":"Wybór uprawnień",    "props":{"actor":"department_manager"}},
        {"id":"n3", "type":"manager_approve",        "label":"Kierownik referatu", "props":{}},
        {"id":"n4", "type":"higher_manager_approve", "label":"Kier. wyższego rzędu","props":{"skip_if_not_required":true}},
        {"id":"n5", "type":"it_execute",             "label":"Realizacja IT",      "props":{}},
        {"id":"n6", "type":"end",                    "label":"Koniec",             "props":{}}
      ],
      "edges": [
        {"from":"n1","to":"n2"}, {"from":"n2","to":"n3"},
        {"from":"n3","to":"n4"}, {"from":"n4","to":"n5"}, {"from":"n5","to":"n6"}
      ]
    }

Silnik po utworzeniu instancji:
  1. Ustawia current_node_id na węzeł „start"
  2. Wywołuje auto_advance() → pomija start, wchodzi w pierwszy interaktywny
     węzeł, po drodze ocenia skip_if.
  3. Czeka na akcję użytkownika (approve / reject / select / execute).
  4. Po akcji zapisuje WorkflowStep z podpisem łańcuchowym, przechodzi dalej.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime
from typing import Any, Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from models import (
    NODE_TYPES,
    AccessRequest,
    Department,
    RequestItem,
    RequestStatus,
    User,
    WorkflowInstance,
    WorkflowInstanceStatus,
    WorkflowStep,
    WorkflowStepAction,
    WorkflowTemplate,
    has_role,
)

from services.after_commit import defer   # powiadomienia dopiero po commicie
_log = logging.getLogger("szup.workflow")


def _resolve_sign_secret() -> str:
    """Sekret łańcucha podpisów kroków obiegu.

    M2 — poprzednio istniał WSPÓLNY, PUBLICZNIE ZNANY fallback
    ("…change-me"), przez co łańcuch podpisów był podrabialny na każdej
    instalacji bez ustawionego env. Kolejność wyboru:

      1. env  SZUP_WORKFLOW_SECRET  — zalecane w produkcji (spójne między
         procesami/replikami),
      2. plik  <SZUP_DATA_DIR>/workflow_secret.key  — automatycznie generowany
         losowy sekret per-instalacja (usuwa znany-stały-klucz),
      3. ostatecznie losowy sekret w pamięci (gdy katalogu nie da się zapisać) —
         z ostrzeżeniem, bo nie przetrwa restartu.
    """
    env = os.getenv("SZUP_WORKFLOW_SECRET")
    if env and env.strip():
        return env.strip()

    import secrets
    from pathlib import Path
    data_dir = Path(os.getenv("SZUP_DATA_DIR", "/opt/szup/data"))
    key_path = data_dir / "workflow_secret.key"
    try:
        if key_path.exists():
            val = key_path.read_text(encoding="utf-8").strip()
            if val:
                return val
        data_dir.mkdir(parents=True, exist_ok=True)
        val = secrets.token_hex(32)
        key_path.write_text(val, encoding="utf-8")
        try:
            os.chmod(key_path, 0o600)
        except Exception:
            pass  # np. Windows — brak POSIX chmod
        _log.warning(
            "SZUP_WORKFLOW_SECRET nie ustawiony — wygenerowano losowy sekret w %s. "
            "W produkcji ustaw jawnie zmienną środowiskową SZUP_WORKFLOW_SECRET.",
            key_path,
        )
        return val
    except Exception as exc:
        _log.error(
            "Nie udało się utrwalić sekretu obiegu (%s) — używam sekretu ulotnego "
            "(nie przetrwa restartu). Ustaw SZUP_WORKFLOW_SECRET.", exc,
        )
        return secrets.token_hex(32)


_SIGN_SECRET = _resolve_sign_secret()


# ---------------------------------------------------------------------------
# Graf: parsowanie, walidacja
# ---------------------------------------------------------------------------

class WorkflowGraphError(ValueError):
    pass


def parse_graph(graph_json: str) -> dict:
    """Deserializuje i waliduje graf. Rzuca WorkflowGraphError przy błędach."""
    try:
        data = json.loads(graph_json)
    except json.JSONDecodeError as exc:
        raise WorkflowGraphError(f"Niepoprawny JSON grafu: {exc}")
    if not isinstance(data, dict):
        raise WorkflowGraphError("Graf musi być obiektem JSON z polami 'nodes' i 'edges'.")
    nodes = data.get("nodes") or []
    edges = data.get("edges") or []
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise WorkflowGraphError("Pola 'nodes' i 'edges' muszą być listami.")
    if not nodes:
        raise WorkflowGraphError("Graf jest pusty — brak węzłów.")

    seen_ids = set()
    starts = 0
    ends = 0
    for n in nodes:
        if not isinstance(n, dict):
            raise WorkflowGraphError("Każdy węzeł musi być obiektem JSON.")
        nid = n.get("id")
        ntype = n.get("type")
        if not nid or not isinstance(nid, str):
            raise WorkflowGraphError("Węzeł bez id lub id nie jest napisem.")
        if nid in seen_ids:
            raise WorkflowGraphError(f"Zduplikowany id węzła: {nid}")
        seen_ids.add(nid)
        if ntype not in NODE_TYPES:
            raise WorkflowGraphError(
                f"Nieznany typ węzła '{ntype}'. Dozwolone: {', '.join(NODE_TYPES)}"
            )
        if ntype == "start": starts += 1
        if ntype == "end":   ends += 1

    if starts != 1:
        raise WorkflowGraphError(f"Graf musi mieć dokładnie jeden 'start' (jest: {starts}).")
    if ends < 1:
        raise WorkflowGraphError("Graf musi mieć przynajmniej jeden 'end'.")

    out_edges: dict[str, list[str]] = {}
    for e in edges:
        if not isinstance(e, dict):
            raise WorkflowGraphError("Każda krawędź musi być obiektem JSON.")
        f, t = e.get("from"), e.get("to")
        if not f or not t or f not in seen_ids or t not in seen_ids:
            raise WorkflowGraphError(f"Krawędź {f} → {t}: id nie pasuje do żadnego węzła.")
        out_edges.setdefault(f, []).append(t)

    # --- Spójność i osiągalność (silnik jest liniowy: każdy węzeł nie-'end'
    #     ma dokładnie jedno wyjście; ze startu musi być osiągalny 'end';
    #     brak cykli i martwych/nieosiągalnych węzłów). Bez tej walidacji graf
    #     bez wyjścia powodował cichy auto-complete wniosku bez realizacji. ---
    node_by_id = {n["id"]: n for n in nodes}
    start_id = next(n["id"] for n in nodes if n["type"] == "start")

    for n in nodes:
        outs = out_edges.get(n["id"], [])
        label = n.get("label") or n["id"]
        if n["type"] == "end":
            if outs:
                raise WorkflowGraphError(f"Węzeł końcowy '{label}' nie może mieć krawędzi wyjściowej.")
        else:
            if len(outs) == 0:
                raise WorkflowGraphError(
                    f"Węzeł '{label}' ({n['type']}) nie ma krawędzi wyjściowej — "
                    f"obieg utknąłby albo zamknął się bez realizacji.")
            if len(outs) > 1:
                raise WorkflowGraphError(
                    f"Węzeł '{label}' ({n['type']}) ma {len(outs)} wyjść — obieg jest liniowy, "
                    f"dozwolone dokładnie jedno.")

    # Osiągalność ze startu (iteracyjny DFS) + wymóg osiągalnego 'end'.
    reachable: set[str] = set()
    stack = [start_id]
    while stack:
        cur = stack.pop()
        if cur in reachable:
            continue
        reachable.add(cur)
        for t in out_edges.get(cur, []):
            if t not in reachable:
                stack.append(t)
    if not any(node_by_id[nid]["type"] == "end" for nid in reachable):
        raise WorkflowGraphError("Ze 'start' nie da się dojść do żadnego węzła 'end'.")
    unreachable = [n["id"] for n in nodes if n["id"] not in reachable]
    if unreachable:
        labels = ", ".join(node_by_id[i].get("label") or i for i in unreachable)
        raise WorkflowGraphError(f"Węzły nieosiągalne ze 'start' (martwe gałęzie): {labels}.")

    # Detekcja cyklu (graf musi być acykliczny) — DFS z kolorowaniem.
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n["id"]: WHITE for n in nodes}
    parent_stack: list[tuple[str, list[str]]] = [(start_id, list(out_edges.get(start_id, [])))]
    color[start_id] = GRAY
    while parent_stack:
        u, kids = parent_stack[-1]
        if kids:
            v = kids.pop()
            if color[v] == GRAY:
                raise WorkflowGraphError("Graf obiegu zawiera cykl — niedozwolone.")
            if color[v] == WHITE:
                color[v] = GRAY
                parent_stack.append((v, list(out_edges.get(v, []))))
        else:
            color[u] = BLACK
            parent_stack.pop()

    return data


def validate_request_graph(graph: dict) -> None:
    """Walidacja BIZNESOWA grafu szablonu, z którego korzystają typy wniosków
    (`parse_graph` sprawdza tylko strukturę). Rzuca WorkflowGraphError.

    Obieg jest liniowy, więc „każda ścieżka” to jedna ścieżka od startu do końca.
    Musi na niej stać:
      - etap kierownika komórki (`select_permissions` albo `manager_approve`) —
        inaczej uprawnienia trafiłyby do IT bez decyzji przełożonego pracownika,
      - realizacja IT (`it_execute`) PO etapie kierownika i jako ostatni krok
        przed końcem — inaczej wniosek kończyłby się jako „zrealizowany”, choć
        nikt nie nadał uprawnień w systemach, a rejestr i migawki rozjechałyby
        się z „Moimi uprawnieniami”.
    """
    nodes = {n["id"]: n for n in graph.get("nodes") or []}
    cur = find_start(graph)
    path: list[str] = []
    seen: set[str] = set()
    while cur is not None and cur["id"] not in seen and cur["type"] != "end":
        seen.add(cur["id"])
        if cur["type"] != "start":
            path.append(cur["type"])
        cur = next_node(graph, cur["id"])
    if not nodes or cur is None or cur["type"] != "end":
        raise WorkflowGraphError("Obieg nie dochodzi do węzła końcowego.")
    stage_idx = [i for i, t in enumerate(path) if t in MANAGER_STAGE_TYPES]
    if not stage_idx:
        raise WorkflowGraphError(
            "Obieg musi zawierać etap kierownika komórki (wybór uprawnień albo "
            "akceptację kierownika) — bez niego uprawnienia trafiłyby do IT bez "
            "decyzji przełożonego pracownika.")
    if not path or path[-1] != "it_execute":
        raise WorkflowGraphError(
            "Ostatnim krokiem przed zakończeniem obiegu musi być realizacja przez IT "
            "(it_execute) — inaczej wniosek zamknąłby się jako zrealizowany bez "
            "nadania uprawnień w systemach.")
    if "it_execute" in path[:stage_idx[-1]]:
        raise WorkflowGraphError(
            "Realizacja przez IT nie może poprzedzać etapu kierownika komórki.")


def check_request_graph_json(graph_json: str) -> dict:
    """`parse_graph` + `validate_request_graph` — dla szablonów przypisywanych do
    typów wniosków (tworzenie/edycja szablonu, zmiana szablonu typu, nowy
    wniosek). Rzuca WorkflowGraphError z polskim komunikatem."""
    graph = parse_graph(graph_json)
    validate_request_graph(graph)
    return graph


def find_start(graph: dict) -> dict:
    for n in graph["nodes"]:
        if n["type"] == "start":
            return n
    raise WorkflowGraphError("Brak węzła 'start'")


def next_node(graph: dict, node_id: str) -> Optional[dict]:
    """Zwraca pierwszy węzeł do którego wiedzie krawędź z node_id. None gdy brak."""
    for e in graph["edges"]:
        if e["from"] == node_id:
            for n in graph["nodes"]:
                if n["id"] == e["to"]:
                    return n
    return None


def find_node(graph: dict, node_id: str) -> Optional[dict]:
    for n in graph["nodes"]:
        if n["id"] == node_id:
            return n
    return None


# ---------------------------------------------------------------------------
# Podpisy łańcuchowe
# ---------------------------------------------------------------------------

# Wersja podpisu kroku: HMAC-SHA256 z sekretem jako kluczem (3.11). Starsze
# kroki mają podpis sha256(secret|prev|payload) bez przedrostka — weryfikacja
# przyjmuje oba formaty, więc istniejące łańcuchy pozostają ważne.
SIGN_PREFIX_HMAC = "hmac1:"


def _sign_material(prev_signature: Optional[str], step_data: dict) -> str:
    payload = json.dumps(step_data, sort_keys=True, ensure_ascii=False, default=str)
    return f"{prev_signature or ''}|{payload}"


def _sign(prev_signature: Optional[str], step_data: dict) -> str:
    """Podpis łańcuchowy kroku: `hmac1:` + HMAC-SHA256(secret, prev_sig|kanoniczny_step_json).

    Nie jest to podpis kwalifikowany, ale wykrywa manipulację historią
    (wstawianie / modyfikacja kroków) bez znajomości sekretu."""
    import hmac
    mac = hmac.new(_SIGN_SECRET.encode("utf-8"),
                   _sign_material(prev_signature, step_data).encode("utf-8"),
                   hashlib.sha256).hexdigest()
    return SIGN_PREFIX_HMAC + mac


def _sign_legacy(prev_signature: Optional[str], step_data: dict) -> str:
    """Podpis sprzed 3.11: sha256(secret|prev_sig|kanoniczny_step_json) — tylko
    do weryfikacji starych kroków."""
    material = f"{_SIGN_SECRET}|{_sign_material(prev_signature, step_data)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _signature_ok(signature: Optional[str], prev_signature: Optional[str],
                  step_data: dict) -> bool:
    """Czy podpis kroku zgadza się z danymi — format rozpoznawany po przedrostku."""
    import hmac
    if not signature:
        return False
    if signature.startswith(SIGN_PREFIX_HMAC):
        expected = _sign(prev_signature, step_data)
    else:
        expected = _sign_legacy(prev_signature, step_data)
    return hmac.compare_digest(signature, expected)


def _last_signature(session: Session, instance_id: int) -> Optional[str]:
    row = session.exec(
        select(WorkflowStep)
        .where(WorkflowStep.instance_id == instance_id)
        .order_by(WorkflowStep.step_index.desc())
    ).first()
    return row.signature if row else None


def _next_step_index(session: Session, instance_id: int) -> int:
    row = session.exec(
        select(WorkflowStep)
        .where(WorkflowStep.instance_id == instance_id)
        .order_by(WorkflowStep.step_index.desc())
    ).first()
    return (row.step_index + 1) if row else 0


def verify_chain(session: Session, instance_id: int) -> bool:
    """Weryfikuje łańcuch podpisów instancji. Do widoku audytora."""
    steps = session.exec(
        select(WorkflowStep)
        .where(WorkflowStep.instance_id == instance_id)
        .order_by(WorkflowStep.step_index.asc())
    ).all()
    prev = None
    for s in steps:
        data = {
            "step_index": s.step_index,
            "node_id": s.node_id,
            "node_type": s.node_type,
            "action": s.action.value if hasattr(s.action, "value") else s.action,
            "actor_user_id": s.actor_user_id,
            "payload": s.payload,
            "comment": s.comment,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        if s.prev_signature != prev or not _signature_ok(s.signature, prev, data):
            return False
        prev = s.signature
    return True


# ---------------------------------------------------------------------------
# Ocena skip_if — na razie: pojedyncza flaga „skip_if_not_required" dla
# węzła higher_manager_approve czyta Department.requires_higher_approval.
# Rozszerzenia (np. skip_if_asset_not_personal_data) dokładamy tu.
# ---------------------------------------------------------------------------

def is_self_request(request: AccessRequest, user: Optional[User]) -> bool:
    """Czy `user` działa na wniosku, który dotyczy JEGO SAMEGO (jest dowiązanym
    pracownikiem wniosku) — np. kierownik składa wniosek dla siebie albo kadry
    złożyły wniosek dla kierownika, który teraz wybiera uprawnienia."""
    wid = getattr(request, "worker_user_id", None)
    return bool(user is not None and wid and user.id == wid)


def _lead_depts_of(session: Session, user_id: Optional[int]) -> list[Department]:
    """Komórki (aktywne, niezarchiwizowane), którymi `user_id` kieruje albo
    w których jest zastępcą kierownika — w całej strukturze (cache na żądanie)."""
    if not user_id:
        return []
    from services.permissions import _cached

    def compute():
        from sqlmodel import col
        from models import DepartmentDeputy
        ids = {int(x) for x in session.exec(
            select(Department.id).where(Department.manager_user_id == user_id)).all()}
        ids |= {int(x) for x in session.exec(
            select(DepartmentDeputy.department_id)
            .where(DepartmentDeputy.user_id == user_id)).all()}
        if not ids:
            return []
        return [d for d in session.exec(
            select(Department).where(col(Department.id).in_(sorted(ids)))).all()
            if d.is_active and not getattr(d, "archived_at", None)]
    return _cached(session, f"wf_lead_depts:{user_id}", compute)


def _directs_unit(session: Session, user_id: Optional[int]) -> bool:
    """Czy `user_id` jest kierownikiem całej jednostki (dyrektorem)."""
    if not user_id:
        return False
    from models import Unit
    return session.exec(select(Unit.id).where(Unit.manager_user_id == user_id)).first() is not None


def worker_lead_circle(session: Session, request: AccessRequest,
                       dept: Optional[Department] = None) -> set[int]:
    """Kierownictwo (kierownik i zastępcy) KAŻDEJ komórki, którą kieruje
    pracownik wniosku albo w której jest zastępcą — w całej strukturze, nie
    tylko komórki wniosku (3.11, decyzja D1/D2). Pracownik będący dyrektorem
    jednostki należy do kręgu sam. Puste, gdy pracownik nikim nie kieruje.
    Te osoby nie zastępują decyzji przełożonego pracownika."""
    wid = getattr(request, "worker_user_id", None)
    if not wid:
        return set()
    from services.permissions import dept_deputy_ids
    out: set[int] = set()
    for d in _lead_depts_of(session, wid):
        out |= set(dept_deputy_ids(session, d.id))
        if d.manager_user_id:
            out.add(d.manager_user_id)
    if _directs_unit(session, wid):
        out.add(wid)
    return out


def worker_leads_dept(session: Session, request: AccessRequest,
                      dept: Optional[Department] = None) -> bool:
    """Czy pracownik wniosku kieruje dowolną komórką, jest w niej zastępcą
    albo jest dyrektorem jednostki — patrz `worker_lead_circle`."""
    return bool(worker_lead_circle(session, request, dept))


def stands_above_worker(session: Session, user: Optional[User],
                        request: Optional[AccessRequest]) -> bool:
    """Czy `user` stoi w strukturze WYŻEJ niż pracownik wniosku (D1/D2):

    - pracownik bez stanowiska kierowniczego — każdy (zakres sprawdza wołający),
    - pracownik kierujący komórkami (lub zastępca) — `user` musi być
      przełożonym KAŻDEJ z nich (komórka wyżej albo dyrektor jednostki),
    - pracownik będący dyrektorem jednostki — nikt (rezerwa superadmina).
    Sam pracownik nigdy nie stoi nad sobą."""
    wid = getattr(request, "worker_user_id", None) if request is not None else None
    if not wid or user is None:
        return True
    if user.id == wid:
        return False
    if _directs_unit(session, wid):
        return False
    from services.permissions import is_superior_for
    return all(is_superior_for(session, user, d, include_self=False)
               for d in _lead_depts_of(session, wid))


def worker_did_manager_step(session: Session, request: AccessRequest,
                            instance: Optional[WorkflowInstance] = None) -> bool:
    """Czy którykolwiek krok etapu kierownika (wybór / akceptacja) w obiegu
    wniosku wykonał sam pracownik, którego wniosek dotyczy."""
    wid = getattr(request, "worker_user_id", None)
    if not wid:
        return False
    if instance is None:
        if getattr(request, "id", None) is None:
            return False
        instance = instance_of(session, request)
    if instance is None or instance.id is None:
        return False
    from sqlmodel import col
    return session.exec(
        select(WorkflowStep.id)
        .where(WorkflowStep.instance_id == instance.id)
        .where(WorkflowStep.actor_user_id == wid)
        .where(col(WorkflowStep.node_type).in_(list(MANAGER_STAGE_TYPES)))
        .where(col(WorkflowStep.action).in_([WorkflowStepAction.select,
                                             WorkflowStepAction.approve]))
    ).first() is not None


def needs_superior_approval(session: Session, request: AccessRequest,
                            dept: Optional[Department], actor_user: Optional[User] = None,
                            instance: Optional[WorkflowInstance] = None) -> bool:
    """Wniosek „dla siebie” w szerokim sensie — akceptacja wyższa NIE może być
    pominięta (rozdział obowiązków: zatwierdza przełożony), gdy:

    - krok kierownika wykonuje (`actor_user`) pracownik, którego wniosek dotyczy,
    - którykolwiek wcześniejszy krok etapu kierownika wykonał ten pracownik,
    - pracownik kieruje dowolną komórką, jest w niej zastępcą albo jest
      dyrektorem jednostki (3.11) — wtedy krok kierownika wykonany przez jego
      zastępcę albo podwładnego nie zastępuje decyzji przełożonego."""
    return (is_self_request(request, actor_user)
            or worker_leads_dept(session, request, dept)
            or worker_did_manager_step(session, request, instance))


def should_skip(node: dict, request: AccessRequest, dept: Optional[Department],
                actor_user: Optional[User] = None, *,
                self_request: Optional[bool] = None) -> bool:
    """Czy silnik pomija węzeł. `actor_user` — osoba, której akcja przesuwa
    obieg (przy podglądzie `landing_node_type`: osoba, która miałaby działać).

    Akceptacja wyższa (`higher_manager_approve`) jest pomijana w komórce
    jednostopniowej — CHYBA że wniosek jest „dla siebie” (`self_request`,
    wyliczane przez `needs_superior_approval`; bez niego — tylko gdy krok
    wykonuje sam pracownik). Wniosek „dla siebie” zawsze zatwierdza przełożony."""
    props = node.get("props") or {}
    if node["type"] == "higher_manager_approve":
        if props.get("skip_if_not_required", True):
            if not dept or not dept.requires_higher_approval:
                if self_request is None:
                    self_request = is_self_request(request, actor_user)
                return not self_request
    return False


def landing_node_type(
    session: Session,
    instance: WorkflowInstance,
    request: AccessRequest,
    action: str,
    actor_user: Optional[User] = None,
) -> Optional[str]:
    """Typ węzła, na którym zatrzyma się obieg PO wykonaniu `action` z bieżącego
    węzła przez `actor_user` — bez mutacji stanu (podgląd `advance`).

    `reject` nie posuwa obiegu naprzód → None. Dla `select`/`approve` idziemy
    krawędziami od bieżącego węzła, pomijając auto-skip (`should_skip`) aż do
    pierwszego węzła interaktywnego albo `end`. Dzięki temu wiadomo z góry, czy
    ten ruch kieruje wniosek do realizacji IT (`it_execute`).
    """
    if action == "reject" or not instance.current_node_id:
        return None
    graph = json.loads(instance.template_snapshot)
    dept = session.get(Department, request.department_id) if request.department_id else None
    return _landing_from(session, graph, instance.current_node_id, request, dept,
                         actor_user, instance)


def _landing_from(session: Session, graph: dict, node_id: str, request: AccessRequest,
                  dept: Optional[Department], actor_user: Optional[User],
                  instance: Optional[WorkflowInstance]) -> Optional[str]:
    """Rdzeń `landing_node_type` — od węzła `node_id` grafu `graph` (także dla
    wniosku jeszcze niezapisanego: `instance` = None)."""
    node = _landing_node_from(session, graph, node_id, request, dept, actor_user, instance)
    return node["type"] if node else None


def _landing_node_from(session: Session, graph: dict, node_id: str, request: AccessRequest,
                       dept: Optional[Department], actor_user: Optional[User],
                       instance: Optional[WorkflowInstance]) -> Optional[dict]:
    acted = find_node(graph, node_id)
    self_req = needs_superior_approval(session, request, dept, actor_user, instance)
    # Automatyczna akceptacja wyższa (`auto_higher_approval`) liczy się tylko
    # wtedy, gdy `actor_user` faktycznie może wykonać bieżący krok.
    acted_type = (acted or {}).get("type") if actor_user is not None else None
    for _ in range(100):
        nxt = next_node(graph, node_id)
        if not nxt:
            return None
        node_id = nxt["id"]
        if nxt["type"] == "end":
            return nxt
        if should_skip(nxt, request, dept, actor_user, self_request=self_req):
            continue
        if (acted_type and auto_higher_approval(session, request, dept, acted_type,
                                                nxt, actor_user)
                and can_act(acted, request, dept, actor_user, session)[0]):
            acted_type = None
            continue
        return nxt
    return None


def self_request_blocked(session: Session, request: AccessRequest,
                         dept: Optional[Department], user: User, node: Optional[dict],
                         landing: Optional[str],
                         instance: Optional[WorkflowInstance] = None) -> bool:
    """Czy krok kierownika (`node`) na wniosku „dla siebie” ominąłby akceptację
    przełożonego — obieg trafiłby (`landing`) prosto do IT.

    „Dla siebie” w szerokim sensie (`needs_superior_approval`). Nie blokujemy
    przełożonego, który sam mógłby wykonać akceptację wyższą (np. przejął
    wniosek) — jego krok jest decyzją przełożonego — ani superadmina działającego
    jako rezerwa, gdy nad pracownikiem nie ma nikogo (`superadmin_acts`)."""
    if not needs_superior_approval(session, request, dept, user, instance):
        return False
    if landing in ("higher_manager_approve", *MANAGER_STAGE_TYPES):
        return False
    if has_role(user, "superadmin"):
        return not (node is not None and superadmin_acts(session, node, request, dept))
    if is_self_request(request, user):
        return True
    return not can_act({"id": "_higher", "type": "higher_manager_approve"},
                       request, dept, user, session)[0]


def is_superior_creator(session: Session, user: User, dept: Optional[Department]) -> bool:
    """Czy wniosek składany przez `user` dla komórki `dept` jest od razu przez
    niego przejmowany — przełożony (kierownik / zastępca komórki wyżej, dyrektor
    jednostki) składa wniosek dla podległej komórki z własnym kierownikiem."""
    from services.permissions import is_department_manager_or_deputy, is_superior_for
    return bool(
        dept is not None
        and not has_role(user, "superadmin")
        and dept_has_own_manager(session, dept)
        and not is_department_manager_or_deputy(session, user, dept)
        and is_superior_for(session, user, dept, include_self=False))


def preview_new_request(session: Session, user: User, worker: Optional[User],
                        dept: Optional[Department], graph: dict,
                        kind: str = "change") -> dict:
    """Podgląd wniosku, który `user` złożyłby teraz z pozycjami dla `worker`
    w komórce `dept` (bez zapisu): `landing_node_type` — węzeł, na którym
    stanie obieg po złożeniu (z automatycznymi krokami etapu kierownika jak
    w `POST /requests/`), i `will_take_over` — czy składający od razu przejmie
    wniosek. Te same reguły co serwer (MyTeam nie przybliża ich sam)."""
    take = is_superior_creator(session, user, dept)
    req = AccessRequest(
        worker_name=(worker.full_name or worker.username) if worker else "",
        worker_user_id=worker.id if worker else None,
        unit_id=dept.unit_id if dept else 0,
        department_id=dept.id if dept else None,
        kind=kind, created_by_id=user.id,
        taken_over_by_id=user.id if take else None,
    )
    # Wejście w pierwszy interaktywny węzeł (jak `start_instance`, aktor None).
    start = find_start(graph)
    self_req = needs_superior_approval(session, req, dept, None, None)
    node = None
    cur = start["id"]
    for _ in range(100):
        nxt = next_node(graph, cur)
        if not nxt:
            break
        cur = nxt["id"]
        if nxt["type"] == "end" or not should_skip(nxt, req, dept, None, self_request=self_req):
            node = nxt
            break
    landing = node["type"] if node else None
    # Automatyczne kroki etapu kierownika składającego (`_auto_manager_steps`).
    for _ in range(len(MANAGER_STAGE_TYPES) + 1):
        if not node or node["type"] not in MANAGER_STAGE_TYPES:
            break
        if not can_act(node, req, dept, user, session)[0]:
            break
        nxt = _landing_node_from(session, graph, node["id"], req, dept, user, None)
        nxt_type = nxt["type"] if nxt else None
        if self_request_blocked(session, req, dept, user, node, nxt_type):
            break
        landing, node = nxt_type, nxt
    return {"landing_node_type": landing, "will_take_over": take}


AUTO_HIGHER_COMMENT = ("Akceptacja wyższa zaliczona automatycznie — wybór wykonał "
                       "przełożony uprawniony do akceptacji")


def auto_higher_approval(session: Session, request: AccessRequest,
                         dept: Optional[Department], acted_type: Optional[str],
                         nxt: dict, actor_user: Optional[User]) -> bool:
    """Czy akceptację wyższą (`nxt`) zaliczyć automatycznie zaraz po kroku
    kierownika komórki (`acted_type`) wykonanym przez `actor_user`.

    Tak, gdy krok kierownika wysłał ktoś, kto sam może wykonać akceptację
    wyższą (`can_act`) — przełożony, który przejął wniosek albo złożył go dla
    podległej komórki, kierownik wyżej działający w komórce bez kierownika,
    dyrektor jednostki. Akceptowałby wtedy własny wybór drugi raz.

    Nigdy dla wniosku „dla siebie” (pracownik nie zatwierdza sam siebie) ani
    dla kierownika / zastępcy samej komórki — wyjątek: dyrektor jednostki,
    o ile `can_act` pozwala mu na akceptację wyższą. Superadmin w obiegu nie
    działa, więc też nigdy.

    Wniosek „dla siebie” w szerokim sensie (`needs_superior_approval`: dla
    kierownika komórki albo z krokiem wykonanym przez pracownika) zaliczamy
    automatycznie tylko po kroku niezależnego przełożonego — `can_act` odmawia
    akceptacji wyższej pracownikowi i kręgowi samej komórki."""
    if actor_user is None or acted_type not in MANAGER_STAGE_TYPES:
        return False
    if nxt.get("type") != "higher_manager_approve":
        return False
    if has_role(actor_user, "superadmin") or is_self_request(request, actor_user):
        return False
    # Kierownik / zastępca samej komórki — `can_act` odmawia im akceptacji
    # wyższej (poza dyrektorem jednostki), więc wystarczy jego werdykt.
    return can_act(nxt, request, dept, actor_user, session)[0]


def grants_permissions(session: Session, request: AccessRequest) -> bool:
    """Czy wniosek NADAJE co najmniej jedno uprawnienie (pozycja `kind='grant'`,
    której nie odmówiono).

    Czyste odebranie/ustanie stosunku pracy nie nadaje niczego (podobnie
    wniosek, którego wszystkie nadania odmówiono) → oświadczenie wnioskującego
    nie ma zastosowania.
    """
    items = session.exec(
        select(RequestItem).where(RequestItem.request_id == request.id)
    ).all()
    return any((getattr(i, "kind", "grant") or "grant") == "grant"
               and not getattr(i, "denied", False) for i in items)


# ---------------------------------------------------------------------------
# Etap kierownika komórki — wersja robocza, widoczność i przejęcie
# ---------------------------------------------------------------------------

# Węzły „etapu kierownika komórki" — kierownik przygotowuje wniosek (wybór
# uprawnień / akceptacja) i może go zapisywać jako wersję roboczą.
MANAGER_STAGE_TYPES = ("select_permissions", "manager_approve")

# Komunikat 403 dla osób, przed którymi wniosek na etapie kierownika jest ukryty.
DRAFT_HIDDEN_MSG = "Wniosek jest jeszcze u kierownika komórki (roboczy)."


def dept_has_own_manager(session: Session, dept: Optional[Department]) -> bool:
    """Czy komórka ma WŁASNEGO, aktywnego kierownika (i nie jest samodzielnym
    stanowiskiem). Tylko wtedy istnieje etap roboczy kierownika komórki —
    w pozostałych komórkach krok wykonuje od razu kierownik wyżej."""
    from services.permissions import has_active_manager
    if dept is None or getattr(dept, "kind", None) == "standalone":
        return False
    return has_active_manager(session, dept)


def is_manager_stage(session: Session, node_type: Optional[str],
                     dept: Optional[Department]) -> bool:
    """Wniosek stoi na etapie kierownika komórki, która ma własnego kierownika
    (wybór / akceptacja) — wtedy obowiązują reguły wersji roboczej i przejęcia."""
    return node_type in MANAGER_STAGE_TYPES and dept_has_own_manager(session, dept)


# ---------------------------------------------------------------------------
# Instancja obiegu wniosku i jej bieżący węzeł (wspólny helper + cache sesji)
# ---------------------------------------------------------------------------
#
# Cache w `session.info` (na czas jednego żądania):
#   _wf_rows   — {request_id: WorkflowInstance | None} (None = wniosek bez obiegu),
#   _wf_graphs — {instance_id: sparsowany template_snapshot}.
# Snapshot grafu instancji jest zamrożony, a sama instancja to obiekt z mapy
# tożsamości sesji (zawsze aktualny `current_node_id`/`status`), więc węzeł
# wyliczamy na bieżąco z cache'owanego grafu. Cache czyścimy po każdym flushu
# i rollbacku — jak `_perm_cache` w services.permissions — żeby nowo utworzona
# (albo wycofana) instancja nie zostawiała nieaktualnego wpisu.

_WF_CACHE_KEYS = ("_wf_rows", "_wf_graphs")


def _clear_wf_cache(session, *_args) -> None:
    for key in _WF_CACHE_KEYS:
        session.info.pop(key, None)


def _install_wf_cache_invalidation() -> None:
    from sqlalchemy import event
    from sqlalchemy.orm import Session as _OrmSession
    if not event.contains(_OrmSession, "after_flush", _clear_wf_cache):
        event.listen(_OrmSession, "after_flush", _clear_wf_cache)
        event.listen(_OrmSession, "after_rollback", _clear_wf_cache)


_install_wf_cache_invalidation()


def preload_instances(session: Session, request_ids: list[int]) -> None:
    """Wczytaj hurtem instancje obiegu wniosków do cache sesji (lista wniosków —
    bez osobnego zapytania na wiersz). Wniosek bez instancji → None."""
    if not request_ids:
        return
    from sqlmodel import col
    found: dict[int, Optional[WorkflowInstance]] = {i: None for i in request_ids}
    for inst in session.exec(
        select(WorkflowInstance).where(col(WorkflowInstance.request_id).in_(request_ids))
    ).all():
        if found.get(inst.request_id) is None:
            found[inst.request_id] = inst
    session.info.setdefault("_wf_rows", {}).update(found)


def instance_of(session: Session, request: AccessRequest | int) -> Optional[WorkflowInstance]:
    """Instancja obiegu wniosku (w dowolnym stanie) albo None — z cache sesji."""
    rid = request if isinstance(request, int) else request.id
    cache = session.info.setdefault("_wf_rows", {})
    if rid not in cache:
        cache[rid] = session.exec(
            select(WorkflowInstance).where(WorkflowInstance.request_id == rid)
        ).first()
    return cache[rid]


def active_node_of(session: Session, instance: Optional[WorkflowInstance]) -> Optional[dict]:
    """Bieżący węzeł instancji, o ile obieg jest AKTYWNY i ma węzeł; inaczej None
    (także przy uszkodzonym snapshocie grafu)."""
    if (instance is None or instance.status != WorkflowInstanceStatus.active
            or not instance.current_node_id):
        return None
    graphs = session.info.setdefault("_wf_graphs", {})
    graph = graphs.get(instance.id)
    if graph is None:
        try:
            graph = json.loads(instance.template_snapshot)
        except Exception:
            return None
        graphs[instance.id] = graph
    try:
        return find_node(graph, instance.current_node_id)
    except Exception:
        return None


def request_workflow(session: Session, request: AccessRequest | int
                     ) -> tuple[Optional[WorkflowInstance], Optional[dict]]:
    """(instancja, bieżący węzeł) wniosku — JEDYNY helper „wniosek → aktywny
    węzeł” dla silnika i routerów. Instancja zwracana w każdym stanie (np. do
    historii kroków), węzeł tylko dla aktywnego obiegu (patrz `active_node_of`)."""
    inst = instance_of(session, request)
    return inst, active_node_of(session, inst)


def current_node_of(session: Session, request: AccessRequest) -> Optional[dict]:
    """Bieżący węzeł AKTYWNEGO obiegu wniosku (albo None) — skrót do
    `request_workflow`."""
    return request_workflow(session, request)[1]


_UNSET = object()


def effective_taker_id(session: Session, request: AccessRequest,
                       dept: Any = _UNSET) -> Optional[int]:
    """Id osoby, której przejęcie wniosku jest WCIĄŻ ważne, albo None.

    Przejęcie honorujemy tylko wtedy, gdy przejmujący ma aktywne konto i nadal
    jest przełożonym kierownika komórki (`is_superior_for(..., include_self=False)`).
    Gdy przejmujący odszedł, został przeniesiony albo stracił stanowisko,
    wniosek traktujemy jak nieprzejęty: kierownik komórki i jego zastępcy
    odzyskują prawo działania, a przełożeni mogą go przejąć ponownie."""
    from services.permissions import is_superior_for
    taker_id = getattr(request, "taken_over_by_id", None)
    if not taker_id:
        return None
    if dept is _UNSET:
        dept = session.get(Department, request.department_id) if request.department_id else None
    taker = session.get(User, taker_id)
    if not taker or not taker.is_active:
        return None
    if not is_superior_for(session, taker, dept, include_self=False):
        return None
    return taker_id


def _authority_above(session: Session, user: User,
                     dept: Optional[Department]) -> Optional[tuple[int, int]]:
    """Najwyższa pozycja `user` w łańcuchu NAD `dept` jako (poziom, ranga).

    Poziom 1 = komórka nadrzędna, 2 = komórka nad nią itd.; ranga 1 = kierownik,
    0 = zastępca. Dyrektor jednostki stoi ponad całą strukturą komórek.
    None — user nie jest przełożonym kierownika `dept`."""
    from models import Unit
    from services.permissions import dept_deputy_ids
    if dept is None:
        return None
    best: Optional[tuple[int, int]] = None
    seen: set[int] = set()
    level = 0
    cur = session.get(Department, dept.parent_dept_id) if dept.parent_dept_id else None
    while cur is not None and cur.id not in seen:
        seen.add(cur.id)
        level += 1
        pos = None
        if cur.manager_user_id == user.id:
            pos = (level, 1)
        elif user.id in dept_deputy_ids(session, cur.id):
            pos = (level, 0)
        if pos and (best is None or pos > best):
            best = pos
        cur = session.get(Department, cur.parent_dept_id) if cur.parent_dept_id else None
    unit = session.get(Unit, dept.unit_id) if getattr(dept, "unit_id", None) else None
    if unit and unit.manager_user_id == user.id:
        best = (10 ** 6, 1)
    return best


def outranks_taker(session: Session, user: User, taker_id: int,
                   dept: Optional[Department]) -> bool:
    """Czy `user` stoi WYŻEJ niż obecny przejmujący — wtedy może przejąć
    wniosek ponownie (np. kierownik komórki nadrzędnej od swojego zastępcy,
    dyrektor jednostki od kierownika komórki nadrzędnej)."""
    if user.id == taker_id:
        return False
    mine = _authority_above(session, user, dept)
    if mine is None:
        return False
    taker = session.get(User, taker_id)
    theirs = _authority_above(session, taker, dept) if taker else None
    return theirs is None or mine > theirs


def manager_stage_visibility(session: Session, request: AccessRequest, user: User,
                             node_type: Any = _UNSET,
                             dept: Any = _UNSET) -> Optional[bool]:
    """Widoczność wniosku na etapie kierownika komórki — JEDYNE źródło prawdy
    tej reguły (pozostałe funkcje są jej pochodnymi):

    - `can_view_request` — ta sama reguła jako bool (False = ukryty),
    - `manager_stage_hidden_clause` — jej odpowiednik w SQL dla listy wniosków
      (zgodność pilnuje test równoważności w tests/test_cleanup35_visibility.py),
    - router (`_check_access`) czyta wynik trójstanowo: None → zwykłe reguły
      ról, True → dostęp bez dalszych warunków, False → 403.

    Zwraca None, gdy wniosek NIE jest na takim etapie (obowiązują zwykłe reguły
    dostępu), True — gdy jest i `user` może go zobaczyć, False — gdy jest
    i wniosek ma być przed `user` ukryty (np. IT, administrator, inni kierownicy).

    Widzą go: superadmin (tylko podgląd), twórca wniosku (np. kadry), kierownik
    komórki i jego zastępcy, osoba, która wniosek przejęła, oraz przełożeni
    (kierownik / zastępca komórki wyżej w strukturze, dyrektor jednostki) — ci
    ostatni tylko do odczytu, dopóki wniosku nie przejmą.

    Zapisana wersja robocza (`draft_saved_at`) jest ukryta w tym samym kręgu
    także wtedy, gdy komórka NIE ma (już) własnego aktywnego kierownika — np. po
    dezaktywacji kierownika (urlop) albo gdy wersję roboczą zapisał przełożony
    w komórce bez kierownika. Krąg nie zależy od aktywności konta kierownika:
    zastępcy komórki, odpowiedzialny przełożony (i każdy wyżej), twórca,
    superadmin.
    """
    from services.permissions import is_department_manager_or_deputy, is_superior_for

    if dept is _UNSET:
        dept = session.get(Department, request.department_id) if request.department_id else None
    if node_type is _UNSET:
        node = current_node_of(session, request)
        node_type = node.get("type") if node else None
    if node_type not in MANAGER_STAGE_TYPES:
        return None
    if not (dept_has_own_manager(session, dept) or getattr(request, "draft_saved_at", None)):
        return None
    if has_role(user, "superadmin"):
        return True
    if request.created_by_id and request.created_by_id == user.id:
        return True
    # Ważny przejmujący jest zawsze przełożonym (patrz `effective_taker_id`),
    # więc obejmuje go warunek poniżej — przejęcie, które wygasło, nic nie daje.
    if is_department_manager_or_deputy(session, user, dept):
        return True
    return bool(is_superior_for(session, user, dept, include_self=False))


def can_view_request(session: Session, request: AccessRequest, user: User,
                     node_type: Any = _UNSET, dept: Any = _UNSET) -> bool:
    """`manager_stage_visibility` jako bool: False tylko wtedy, gdy wniosek jest
    na etapie kierownika komórki i ma być przed `user` ukryty. Pozostałe reguły
    dostępu (role, zakres komórek) sprawdza router."""
    return manager_stage_visibility(session, request, user, node_type, dept) is not False


def manager_stage_hidden_clause(session: Session, user: User):
    """Warunek SQL (dla `select(AccessRequest).where(...)`) wycinający wnioski,
    które `can_view_request` ukryłby przed `user` — żeby LIMIT/OFFSET listy
    liczył już tylko widoczne wiersze. None — nic nie trzeba wycinać
    (superadmin).

    Wniosek stoi „na etapie kierownika”, gdy `AccessRequest.current_node_type`
    to wybór / akceptacja kierownika. Ukryty jest, gdy nie złożył go `user`,
    a jego komórka leży poza „kręgiem” `user` (`superior_dept_ids`: komórki,
    którymi kieruje lub jest zastępcą, ich poddrzewo i komórki jednostki, którą
    kieruje) oraz:
      - komórka ma własnego, aktywnego kierownika (etap roboczy), albo
      - wniosek ma zapisaną wersję roboczą (`draft_saved_at`) — także w komórce,
        która kierownika nie ma (już) — patrz `manager_stage_visibility`.

    Siatka bezpieczeństwa: wniosek z pustym `current_node_type` (kolumna
    niewypełniona — np. nieudany backfill po migracji), który ma AKTYWNĄ
    instancję obiegu, traktujemy jak wniosek na etapie kierownika. Pusty typ
    bez aktywnej instancji (wniosek zakończony, odrzucony albo stary wniosek
    sprzed silnika obiegu) nie jest ukrywany — inaczej stare wnioski w toku
    znikałyby z list IT i administratora. Podgląd pojedynczego wniosku liczy
    regułę z instancji obiegu (`manager_stage_visibility`)."""
    from sqlalchemy import and_, exists, false, func, not_, or_, true
    from sqlmodel import col
    from services.permissions import superior_dept_ids
    if has_role(user, "superadmin"):
        return None
    staged = session.exec(
        select(Department).join(User, User.id == Department.manager_user_id)
        .where(User.is_active == True)  # noqa: E712
    ).all()
    own_mgr = {d.id for d in staged if getattr(d, "kind", None) != "standalone"}
    circle = set(superior_dept_ids(session, user))
    hidden_own = sorted(own_mgr - circle)

    node_type = col(AccessRequest.current_node_type)
    dept_id = func.coalesce(col(AccessRequest.department_id), -1)
    active_instance = exists().where(
        WorkflowInstance.request_id == AccessRequest.id,
        WorkflowInstance.status == WorkflowInstanceStatus.active,
    )
    at_manager_stage = or_(
        and_(node_type.is_not(None), node_type.in_(list(MANAGER_STAGE_TYPES))),
        and_(node_type.is_(None), active_instance),
    )
    outside_staged = dept_id.notin_(hidden_own) if hidden_own else true()
    in_circle = dept_id.in_(sorted(circle)) if circle else false()
    return or_(
        not_(at_manager_stage),
        col(AccessRequest.created_by_id) == user.id,
        and_(outside_staged,
             or_(col(AccessRequest.draft_saved_at).is_(None), in_circle)),
    )


def can_take_over(session: Session, request: AccessRequest, user: User,
                  node_type: Any = _UNSET, dept: Any = _UNSET) -> tuple[bool, int, str]:
    """Czy `user` może przejąć wniosek (przycisk „Przejmij").

    Zwraca (dozwolone, kod HTTP odmowy, powód). Przejąć może przełożony
    (kierownik / zastępca komórki wyżej, dyrektor jednostki) — nie kierownik
    ani zastępca samej komórki — i tylko na etapie kierownika komórki, która
    ma własnego kierownika. Wniosek przejęty już przez kogoś → 409, chyba że
    `user` stoi wyżej niż przejmujący (ponowne przejęcie) albo przejęcie
    wygasło (`effective_taker_id`).
    """
    from services.permissions import is_department_manager_or_deputy, is_superior_for

    if has_role(user, "superadmin"):
        return False, 403, SUPERADMIN_NO_ACT_MSG
    if dept is _UNSET:
        dept = session.get(Department, request.department_id) if request.department_id else None
    if node_type is _UNSET:
        node = current_node_of(session, request)
        node_type = node.get("type") if node else None
    if not is_manager_stage(session, node_type, dept):
        return False, 409, ("Wniosek można przejąć tylko wtedy, gdy czeka na kierownika "
                            "komórki (wybór lub akceptacja uprawnień).")
    taker_id = effective_taker_id(session, request, dept)
    if taker_id:
        if taker_id == user.id:
            return False, 409, "Ten wniosek został już przez Ciebie przejęty."
        if not outranks_taker(session, user, taker_id, dept):
            return False, 409, (f"Wniosek przejął(-ęła) już "
                                f"{request.taken_over_by_name or 'inny przełożony'}.")
    if is_department_manager_or_deputy(session, user, dept):
        return False, 403, ("Kierownik komórki i jego zastępcy obsługują wniosek "
                            "bezpośrednio — przejęcie nie jest potrzebne.")
    if not is_superior_for(session, user, dept, include_self=False):
        return False, 403, ("Wniosek może przejąć tylko przełożony kierownika komórki "
                            "(kierownik komórki wyżej w strukturze lub dyrektor jednostki).")
    return True, 0, ""


def can_release(session: Session, request: AccessRequest, user: User,
                node_type: Any = _UNSET, dept: Any = _UNSET) -> bool:
    """Czy `user` może oddać przejęcie („Oddaj”) — wyłącznie przejmujący
    (superadmin nie działa w obiegu), tylko póki wniosek stoi na etapie
    kierownika komórki."""
    if not getattr(request, "taken_over_by_id", None):
        return False
    if request.taken_over_by_id != user.id:
        return False
    if dept is _UNSET:
        dept = session.get(Department, request.department_id) if request.department_id else None
    if node_type is _UNSET:
        node = current_node_of(session, request)
        node_type = node.get("type") if node else None
    return is_manager_stage(session, node_type, dept)


def claim_take_over(session: Session, request: AccessRequest, user: User,
                    *, expected_taker_id: Optional[int], expected_node_id: str) -> bool:
    """Warunkowy zapis przejęcia (ochrona przed wyścigiem dwóch przełożonych
    albo przejęcia z równoległą wysyłką kierownika).

    `UPDATE accessrequest SET taken_over_* … WHERE taken_over_by_id IS <odczytany>
    AND obieg nadal stoi na <odczytanym> węźle`. Zwraca False, gdy w międzyczasie
    ktoś inny przejął wniosek albo obieg poszedł dalej (wołający zwraca 409).
    """
    from sqlalchemy import exists, update
    now = datetime.utcnow()
    taker_cond = (AccessRequest.taken_over_by_id.is_(None) if expected_taker_id is None
                  else AccessRequest.taken_over_by_id == expected_taker_id)
    node_ok = exists().where(
        WorkflowInstance.request_id == AccessRequest.id,
        WorkflowInstance.current_node_id == expected_node_id,
        WorkflowInstance.status == WorkflowInstanceStatus.active,
    )
    stmt = (update(AccessRequest)
            .where(AccessRequest.id == request.id, taker_cond, node_ok)
            .values(taken_over_by_id=user.id,
                    taken_over_by_name=user.full_name or user.username,
                    taken_over_at=now)
            .execution_options(synchronize_session=False))
    res = session.connection().execute(stmt)
    session.expire(request, ["taken_over_by_id", "taken_over_by_name", "taken_over_at"])
    return res.rowcount == 1


def clear_take_over(request: AccessRequest) -> None:
    request.taken_over_by_id = None
    request.taken_over_by_name = None
    request.taken_over_at = None


def unclaim_take_over(session: Session, request: AccessRequest, *,
                      expected_taker_id: int, expected_node_id: str) -> bool:
    """Warunkowe oddanie przejęcia („Oddaj”) — lustro `claim_take_over`.

    `UPDATE accessrequest SET taken_over_* = NULL WHERE taken_over_by_id =
    <odczytany> AND obieg nadal stoi na <odczytanym> węźle`. Zwraca False, gdy
    w międzyczasie ktoś wyżej przejął wniosek ponownie albo obieg poszedł dalej
    (wołający zwraca 409 i nie wysyła powiadomień)."""
    from sqlalchemy import exists, update
    node_ok = exists().where(
        WorkflowInstance.request_id == AccessRequest.id,
        WorkflowInstance.current_node_id == expected_node_id,
        WorkflowInstance.status == WorkflowInstanceStatus.active,
    )
    stmt = (update(AccessRequest)
            .where(AccessRequest.id == request.id,
                   AccessRequest.taken_over_by_id == expected_taker_id, node_ok)
            .values(taken_over_by_id=None, taken_over_by_name=None, taken_over_at=None)
            .execution_options(synchronize_session=False))
    res = session.connection().execute(stmt)
    session.expire(request, ["taken_over_by_id", "taken_over_by_name", "taken_over_at"])
    return res.rowcount == 1


def drop_expired_take_over(session: Session, request: AccessRequest,
                           dept: Any = _UNSET) -> bool:
    """Po wyjściu wniosku z etapu kierownika komórki: przejęcie, które już
    wygasło (`effective_taker_id` → None), usuwamy z bazy — inaczej IT
    i pozostali widzieliby „Przejęty przez” osobę, która nie miała już do
    tego prawa. Ważne przejęcie zostaje (informacja historyczna). Tylko
    `session.add`; commit robi wywołujący. Zwraca True, gdy wyczyszczono."""
    if not getattr(request, "taken_over_by_id", None):
        return False
    if effective_taker_id(session, request, dept) is not None:
        return False
    clear_take_over(request)
    session.add(request)
    return True


# ---------------------------------------------------------------------------
# Zmiana struktury w trakcie obiegu (kierownik / zastępcy / podległość / typ
# komórki, dyrektor jednostki) — porządki na wnioskach w toku
# ---------------------------------------------------------------------------

# Węzły, na których adresat kroku zależy od struktury: etap kierownika komórki
# i akceptacja wyższa (kierownik komórki nadrzędnej).
STRUCTURE_SENSITIVE_TYPES = MANAGER_STAGE_TYPES + ("higher_manager_approve",)

AUTO_ACTOR_NAME = "SZUP (automatycznie)"


def subtree_dept_ids(session: Session, roots: Any) -> set[int]:
    """Komórki `roots` wraz z całym ich poddrzewem (zmiana kierownika komórki
    zmienia przełożonych wszystkich komórek pod nią)."""
    roots = {int(x) for x in (roots or ()) if x}
    if not roots:
        return set()
    children: dict[int, list[int]] = {}
    for d in session.exec(select(Department)).all():
        if d.parent_dept_id is not None:
            children.setdefault(d.parent_dept_id, []).append(d.id)
    out: set[int] = set()
    stack = list(roots)
    while stack:
        cur = stack.pop()
        if cur in out:
            continue
        out.add(cur)
        stack.extend(children.get(cur, []))
    return out


def unit_dept_ids(session: Session, unit_id: Optional[int]) -> set[int]:
    """Wszystkie komórki jednostki (zmiana dyrektora jednostki)."""
    if not unit_id:
        return set()
    return {int(x) for x in session.exec(
        select(Department.id).where(Department.unit_id == unit_id)).all()}


def _structure_rows(session: Session, dept_ids: Any) -> list[AccessRequest]:
    from sqlmodel import col
    ids = sorted({int(x) for x in (dept_ids or ()) if x})
    if not ids:
        return []
    return list(session.exec(
        select(AccessRequest)
        .where(col(AccessRequest.department_id).in_(ids))
        .where(col(AccessRequest.current_node_type).in_(list(STRUCTURE_SENSITIVE_TYPES)))
    ).all())


def _stage_state(session: Session, request: AccessRequest
                 ) -> Optional[tuple[frozenset, bool]]:
    """(odpowiedzialni za bieżący krok, czy przejęcie jest ważne) — None, gdy
    wniosek nie stoi na węźle zależnym od struktury.

    Odpowiedzialny = ważny przejmujący, a bez niego aktywni adresaci kroku
    (`_stage_actor_ids`)."""
    node = current_node_of(session, request)
    if not node or node.get("type") not in STRUCTURE_SENSITIVE_TYPES:
        return None
    dept = session.get(Department, request.department_id) if request.department_id else None
    taker_ok = False
    if node["type"] in MANAGER_STAGE_TYPES and request.taken_over_by_id:
        taker_ok = (is_manager_stage(session, node["type"], dept)
                    and effective_taker_id(session, request, dept) is not None)
        if taker_ok:
            return frozenset({request.taken_over_by_id}), True
    ids = []
    for uid in _stage_actor_ids(session, node, dept, request):
        u = session.get(User, uid)
        if u and u.is_active:
            ids.append(uid)
    return frozenset(ids), taker_ok


def manager_stage_snapshot(session: Session, dept_ids: Any) -> dict[int, tuple[frozenset, bool]]:
    """Stan „kto odpowiada za krok” wniosków w toku w komórkach `dept_ids` —
    robiony PRZED zmianą struktury i przekazywany do `resync_manager_stage`."""
    out: dict[int, tuple[frozenset, bool]] = {}
    for r in _structure_rows(session, dept_ids):
        st = _stage_state(session, r)
        if st is not None:
            out[r.id] = st
    return out


def resync_manager_stage(session: Session, dept_ids: Any, *,
                         before: Optional[dict] = None,
                         reason: str = "Zmiana w strukturze organizacyjnej") -> int:
    """Porządki na wnioskach w toku po zmianie struktury w komórkach `dept_ids`
    (wołający podaje już całe dotknięte poddrzewo — `subtree_dept_ids` /
    `unit_dept_ids`).

    1. Przejęcie, które przestało być ważne (przejmujący nie jest już
       przełożonym, komórka straciła etap kierownika), albo było nieważne już
       przed zmianą (`before`), jest usuwane ze zdarzeniem „release”
       (aktor: SZUP (automatycznie), notatka z powodem). Dzięki temu
       „uśpione” przejęcie nie ożywa, gdy dawny przełożony odzyska stanowisko.
    2. Gdy zmieniła się osoba odpowiedzialna za bieżący krok, nowi adresaci
       dostają powiadomienie o etapie (po commicie — `defer`); osoby
       odpowiedzialne już wcześniej — nie.

    Tylko `session.add` + flush; commit robi wywołujący. Zwraca liczbę
    zwolnionych przejęć."""
    released = 0
    for r in _structure_rows(session, dept_ids):
        node = current_node_of(session, r)
        if not node:
            continue
        ntype = node.get("type")
        dept = session.get(Department, r.department_id) if r.department_id else None
        prev = (before or {}).get(r.id)
        prev_ids: Optional[frozenset] = prev[0] if prev else None

        if ntype in MANAGER_STAGE_TYPES and r.taken_over_by_id:
            valid_now = (is_manager_stage(session, ntype, dept)
                         and effective_taker_id(session, r, dept) is not None)
            was_stale = prev is not None and not prev[1]
            if not valid_now or was_stale:
                taker_id, taker_name = r.taken_over_by_id, r.taken_over_by_name
                clear_take_over(r)
                session.add(r)
                record_request_event(
                    session, r.id, "release", actor_user=None, actor_name=AUTO_ACTOR_NAME,
                    note=(f"{reason} — przejęcie ({taker_name or f'id={taker_id}'}) "
                          f"straciło ważność; wniosek wraca do kierownika komórki."))
                released += 1
                if prev_ids is None:
                    prev_ids = frozenset({taker_id})

        if prev_ids is None:
            continue   # brak stanu sprzed zmiany i nic nie zwolniono — bez maili
        now = _stage_state(session, r)
        if now is None or now[1]:
            continue   # krok przy ważnym przejmującym — adresat bez zmian
        if now[0] and now[0] != prev_ids:
            _notify_stage(session, r, node, dept, None, exclude_ids=prev_ids)
    if released:
        session.flush()
    return released


def release_take_overs_of(session: Session, user_id: Optional[int], note: str, *,
                          released_ids: Optional[set] = None) -> int:
    """Zwalnia przejęcia osoby `user_id` na wnioskach, które wciąż stoją na
    etapie kierownika komórki (np. przejmujący został dezaktywowany albo stracił
    stanowisko). Kierownik komórki odzyskuje wniosek i dostaje powiadomienie
    o etapie. Zwraca liczbę zwolnionych wniosków; tylko flush, bez commitu."""
    from sqlmodel import col
    if not user_id:
        return 0
    rows = session.exec(
        select(AccessRequest)
        .where(AccessRequest.taken_over_by_id == user_id)
        .where(col(AccessRequest.current_node_type).in_(list(MANAGER_STAGE_TYPES)))
    ).all()
    for r in rows:
        clear_take_over(r)
        session.add(r)
        if released_ids is not None:
            released_ids.add(r.id)
        record_request_event(session, r.id, "release", actor_user=None,
                             actor_name="SZUP (automatycznie)", note=note)
        node = current_node_of(session, r)
        if node:
            dept = session.get(Department, r.department_id) if r.department_id else None
            _notify_stage(session, r, node, dept, None)
    if rows:
        session.flush()
    return len(rows)


# ---------------------------------------------------------------------------
# Historia etapu kierownika (wersja robocza / przejęcie / oddanie)
# ---------------------------------------------------------------------------

REQUEST_EVENT_ACTIONS = ("draft", "take_over", "release")


def record_request_event(session: Session, request_id: int, action: str, *,
                         actor_user: Optional[User] = None,
                         actor_name: Optional[str] = None,
                         note: Optional[str] = None) -> None:
    """Dopisuje zdarzenie do historii wniosku (`RequestEvent`) — poza łańcuchem
    podpisanych kroków obiegu. Tylko `session.add`; commit robi wywołujący."""
    from models import RequestEvent
    if action not in REQUEST_EVENT_ACTIONS:
        raise ValueError(f"Nieznane zdarzenie wniosku: {action}")
    session.add(RequestEvent(
        request_id=request_id, action=action,
        actor_user_id=actor_user.id if actor_user else None,
        actor_name=(actor_name if actor_name is not None else
                    ((actor_user.full_name or actor_user.username) if actor_user else None)),
        note=note,
    ))


def serialize_request_events(session: Session, request_id: int) -> list[dict]:
    """Historia etapu kierownika: [{action, actor_name, at, note}] chronologicznie."""
    from models import RequestEvent
    rows = session.exec(
        select(RequestEvent).where(RequestEvent.request_id == request_id)
        .order_by(RequestEvent.created_at, RequestEvent.id)
    ).all()
    return [{"action": e.action, "actor_name": e.actor_name,
             "at": e.created_at.isoformat() if e.created_at else None,
             "note": e.note} for e in rows]


# ---------------------------------------------------------------------------
# Uprawnienia — kto może wykonać akcję na węźle danego typu
# ---------------------------------------------------------------------------

SUPERADMIN_NO_ACT_MSG = (
    "Superadmin jest kontem konfiguracyjnym (break-glass) i nie działa w obiegu "
    "wniosków — może je jedynie podglądać.")


def superadmin_acts(session: Session, node: dict, request: AccessRequest,
                    dept: Optional[Department]) -> bool:
    """Czy na tym kroku działa superadmin — wyłącznie rezerwa `_stage_actor_info`
    na etapie kierownika albo akceptacji wyższej, gdy w strukturze nie ma nikogo,
    kto mógłby wykonać krok:

    - akceptacja wyższa wniosku „dla siebie” kierownika, nad którym nie ma
      przełożonego (np. dyrektor jednostki kierujący komórką),
    - krok bez żadnej osoby uprawnionej (np. ta sama osoba kieruje komórką
      i komórką nadrzędną, a jednostka nie ma dyrektora; usunięta komórka
      nadrzędna; komórka bez kierownika w jednostce bez dyrektora),
    - etap kierownika wniosku, który musi zatwierdzić przełożony pracownika,
      w obiegu bez akceptacji wyższej, gdy nad pracownikiem nie ma nikogo (M1).

    Poza tym superadmin w obiegu nie działa. Każdy krok superadmina jest
    oznaczany jako awaryjny (`superadmin_emergency` w payloadzie kroku,
    adnotacja w oświadczeniu)."""
    if node.get("type") not in STRUCTURE_SENSITIVE_TYPES:
        return False
    return bool(_stage_actor_info(session, node, dept, request)[1])


def can_act(node: dict, request: AccessRequest, dept: Optional[Department],
            user: User, session: Session) -> tuple[bool, str]:
    """Zwraca (dozwolone, powód-jeśli-nie).

    Wariant A (czysty rozdział obowiązków): działać w obiegu mogą wyłącznie role
    OPERACYJNE (kierownik / zastępca / pracownik IT). Administrator KONFIGURUJE
    system i NIE działa w obiegu — jeśli ma realizować/akceptować, dostaje
    właściwą rolę operacyjną.

    Superadmin to konto KONFIGURACYJNE (break-glass) — wnioski widzi, ale w
    obiegu nie działa (`superadmin_acts`). Jedyny wyjątek, żeby wniosek nie
    utknął: akceptacja wyższa wniosku „dla siebie” kierownika, nad którym
    w strukturze nie ma nikogo (np. dyrektora jednostki) — patrz
    `_stage_actor_info`.

    Zastępcy (DepartmentDeputy) traktowani na równi z głównym kierownikiem
    komórki — mogą wykonać krok `select_permissions` / `manager_approve`
    dla swojej komórki oraz `higher_manager_approve` gdy są zastępcą
    kierownika wydziału nadrzędnego.
    """
    from services.permissions import (
        is_department_manager_or_deputy, effective_manager_dept, is_superior_for,
    )

    ntype = node["type"]

    if has_role(user, "superadmin"):
        if superadmin_acts(session, node, request, dept) and not is_self_request(request, user):
            return True, ""
        return False, SUPERADMIN_NO_ACT_MSG

    if ntype in MANAGER_STAGE_TYPES:
        if dept_has_own_manager(session, dept):
            # Komórka z własnym kierownikiem — etap roboczy kierownika komórki.
            # Po przejęciu krok wykonuje WYŁĄCZNIE przejmujący przełożony
            # (o ile przejęcie jest wciąż ważne — `effective_taker_id`).
            taker_id = effective_taker_id(session, request, dept)
            if taker_id:
                if taker_id == user.id:
                    return True, ""
                who = request.taken_over_by_name or "przełożony"
                return False, f"Wniosek przejął(-ęła) {who} — krok wykona przełożony."
            if is_department_manager_or_deputy(session, user, dept):
                return True, ""
            # Przełożony widzi wniosek tylko do odczytu — działać może dopiero
            # po jego przejęciu („Przejmij").
            if is_superior_for(session, user, dept, include_self=False):
                return False, ("Wniosek jest u kierownika komórki. Aby wykonać ten krok, "
                               "najpierw przejmij wniosek („Przejmij”).")
            return False, "Tylko kierownik komórki lub jego zastępca może wykonać ten krok."
        # Samodzielne stanowisko / komórka bez (aktywnego) kierownika → krok
        # wykonuje najbliższy kierownik wyżej w strukturze.
        resp = dept
        if dept:
            resp = effective_manager_dept(session, dept) or dept
        if is_department_manager_or_deputy(session, user, resp):
            return True, ""
        # Tu nie ma etapu roboczego kierownika komórki, więc każdy przełożony
        # (kierownik / zastępca komórki wyżej, dyrektor jednostki) działa od razu.
        if is_superior_for(session, user, dept):
            return True, ""
        return False, ("Tylko kierownik, jego zastępca lub przełożony w strukturze może wykonać ten krok.")

    if ntype == "higher_manager_approve":
        # Nikt nie zatwierdza akceptacji wyższej wniosku, który dotyczy jego
        # samego — także dyrektor jednostki (rozdział obowiązków).
        if is_self_request(request, user):
            return False, ("Nie możesz zatwierdzić wniosku, który dotyczy Ciebie — "
                           "zrobi to przełożony.")
        # Kierownik (lub zastępca) SAMEJ komórki nie zatwierdza akceptacji
        # wyższej wniosku własnej komórki — także wtedy, gdy jest jednocześnie
        # kierownikiem / zastępcą komórki nadrzędnej (inaczej zatwierdziłby
        # wniosek „sam u siebie” dwa razy). Jedyny wyjątek: dyrektor jednostki
        # (świadoma decyzja — nad nim nie ma już nikogo w strukturze).
        if (is_department_manager_or_deputy(session, user, dept)
                and _unit_director_id(session, dept) != user.id):
            return False, ("Kierownik komórki i jego zastępcy nie zatwierdzają akceptacji "
                           "wyższej wniosku własnej komórki — zrobi to przełożony.")
        # Wniosek dla kierownika (zastępcy) komórki odpowiedzialnej za wniosek —
        # jego zastępca czy kierownik tej samej komórki nie jest jego przełożonym.
        if (user.id in worker_lead_circle(session, request, dept)
                and _unit_director_id(session, dept) != user.id):
            return False, ("Wniosek dotyczy osoby z kierownictwa Twojej komórki — "
                           "zatwierdzi go przełożony.")
        # D1/D2 (3.11): akceptację wyższą wykonuje wyłącznie osoba stojąca
        # w strukturze WYŻEJ niż pracownik wniosku (np. nie podwładny dyrektora
        # ani kierownika komórki nadrzędnej, który formalnie siedzi w komórce).
        if not stands_above_worker(session, user, request):
            return False, ("Akceptację wyższą wykonuje przełożony pracownika, którego "
                           "dotyczy wniosek — osoba stojąca w strukturze wyżej niż on.")
        parent = None
        if dept and dept.parent_dept_id:
            parent = session.get(Department, dept.parent_dept_id)
        if is_department_manager_or_deputy(session, user, parent):
            return True, ""
        # Każdy przełożony NAD komórką (wyżej niż jej kierownik) oraz dyrektor
        # jednostki (`is_superior_for` liczy dyrektora niezależnie od include_self).
        if is_superior_for(session, user, dept, include_self=False):
            return True, ""
        return False, ("Tylko kierownik wydziału nadrzędnego, jego zastępca lub przełożony wyżej może wykonać ten krok.")

    if ntype == "it_execute":
        if has_role(user, "it_staff"):
            return True, ""
        return False, "Tylko pracownik IT może zrealizować wniosek."

    return False, f"Nie zdefiniowano uprawnień dla typu węzła '{ntype}'."


# ---------------------------------------------------------------------------
# Tworzenie instancji + auto-advance
# ---------------------------------------------------------------------------

def start_instance(
    session: Session,
    request: AccessRequest,
    template: WorkflowTemplate,
) -> WorkflowInstance:
    graph = parse_graph(template.graph_json)
    start_node = find_start(graph)
    instance = WorkflowInstance(
        request_id=request.id,
        template_id=template.id,
        template_version=template.version,
        template_snapshot=template.graph_json,
        current_node_id=start_node["id"],
        status=WorkflowInstanceStatus.active,
    )
    session.add(instance)
    session.flush()

    # Zapisz krok „start" jako auto_advance.
    _record_step(
        session, instance, start_node,
        action=WorkflowStepAction.auto_advance,
        actor_user=None, payload=None, comment="Utworzono instancję obiegu",
    )
    session.flush()

    # Automatycznie idź do pierwszego interaktywnego węzła (pomijając skip_if).
    advance(session, instance, request, actor_user=None)
    return instance


def _record_step(
    session: Session,
    instance: WorkflowInstance,
    node: dict,
    *,
    action: WorkflowStepAction,
    actor_user: Optional[User],
    payload: Any = None,
    comment: Optional[str] = None,
) -> WorkflowStep:
    prev_sig = _last_signature(session, instance.id)
    idx = _next_step_index(session, instance.id)
    now = datetime.utcnow()
    payload_str = json.dumps(payload, ensure_ascii=False, default=str) if payload is not None else None
    step_data = {
        "step_index": idx,
        "node_id": node["id"],
        "node_type": node["type"],
        "action": action.value,
        "actor_user_id": actor_user.id if actor_user else None,
        "payload": payload_str,
        "comment": comment,
        "created_at": now.isoformat(),
    }
    sig = _sign(prev_sig, step_data)
    step = WorkflowStep(
        instance_id=instance.id,
        step_index=idx,
        node_id=node["id"],
        node_type=node["type"],
        action=action,
        actor_user_id=actor_user.id if actor_user else None,
        actor_name=(actor_user.full_name or actor_user.username) if actor_user else None,
        payload=payload_str,
        comment=comment,
        signature=sig,
        prev_signature=prev_sig,
        created_at=now,
    )
    session.add(step)
    return step


def advance(
    session: Session,
    instance: WorkflowInstance,
    request: AccessRequest,
    actor_user: Optional[User],
) -> None:
    """Przesuwa current_node_id do kolejnego węzła interaktywnego,
    po drodze zapisując auto_skip dla pomijanych.

    Interaktywne = wszystko oprócz start/end oraz węzłów które silnik pomija.
    end → zamyka instancję.

    Po kroku kierownika komórki wykonanym przez osobę, która może też wykonać
    akceptację wyższą (`auto_higher_approval`), ten krok zapisujemy od razu
    jako akceptację z jej nazwiskiem i komentarzem `AUTO_HIGHER_COMMENT`,
    a obieg idzie dalej (zwykle do IT).
    """
    graph = json.loads(instance.template_snapshot)
    dept = session.get(Department, request.department_id) if request.department_id else None
    acted = find_node(graph, instance.current_node_id) if instance.current_node_id else None
    acted_type = (acted or {}).get("type") if actor_user is not None else None
    self_req = needs_superior_approval(session, request, dept, actor_user, instance)

    guard = 0
    while True:
        guard += 1
        if guard > 100:
            _log.error("advance() bezpiecznik: przekroczono 100 kroków w instancji %s", instance.id)
            break

        current = find_node(graph, instance.current_node_id) if instance.current_node_id else None
        if not current:
            break

        nxt = next_node(graph, current["id"])
        if not nxt:
            # Węzeł nie-'end' bez wyjścia. Dla NOWYCH szablonów to niemożliwe
            # (parse_graph odrzuca takie grafy), ale zamrożony snapshot starej,
            # niepoprawnej instancji mógłby tu trafić. NIE zamykamy wniosku po
            # cichu (to była luka — completed bez realizacji) — zgłaszamy błąd,
            # a wniosek zostaje na bieżącym węźle do interwencji administratora.
            _log.error("advance(): węzeł '%s' (%s) w instancji %s nie ma wyjścia — "
                       "niepoprawny graf, wniosek NIE zamknięty.",
                       current.get("label") or current["id"], current.get("type"), instance.id)
            raise HTTPException(
                500,
                "Obieg tego wniosku ma niepoprawny graf (węzeł bez wyjścia). "
                "Wniosek nie został zamknięty — zgłoś administratorowi.")

        instance.current_node_id = nxt["id"]
        session.add(instance)

        if nxt["type"] == "end":
            _record_step(session, instance, nxt,
                         action=WorkflowStepAction.auto_advance,
                         actor_user=actor_user, comment="Koniec obiegu")
            instance.status = WorkflowInstanceStatus.completed
            instance.completed_at = datetime.utcnow()
            session.add(instance)
            _sync_request_status(request, instance)
            _audit_request_event(session, request, "request.completed", actor_user)
            _notify_request_completed(session, request, actor_user)
            return

        if should_skip(nxt, request, dept, actor_user, self_request=self_req):
            _record_step(session, instance, nxt,
                         action=WorkflowStepAction.auto_skip, actor_user=None,
                         comment="Warunek pominięcia spełniony")
            continue  # przejdź do kolejnego

        if acted_type and auto_higher_approval(session, request, dept, acted_type,
                                               nxt, actor_user):
            _record_step(session, instance, nxt,
                         action=WorkflowStepAction.approve, actor_user=actor_user,
                         comment=AUTO_HIGHER_COMMENT)
            acted_type = None   # tylko bezpośrednio po kroku kierownika
            continue

        # Węzeł interaktywny — czekamy na akcję użytkownika. Powiadom aktora.
        _sync_request_status(request, instance)
        _notify_stage(session, request, nxt, dept, actor_user)
        return


# ---------------------------------------------------------------------------
# Powiadomienia e-mail (best-effort, w tle)
# ---------------------------------------------------------------------------

def _actor_sender(actor_user: Optional[User]) -> tuple[Optional[str], Optional[str]]:
    """(nazwa, e-mail) osoby, która wywołała zdarzenie — do prezentacji jako
    nadawca powiadomienia. Gdy brak adresu (np. akcja systemowa), zwraca (None,
    None) i powiadomienie wychodzi z domyślnego adresu aplikacji."""
    if actor_user and getattr(actor_user, "email", None):
        return (actor_user.full_name or actor_user.username), actor_user.email
    return None, None


def _responsible_dept(session: Session, d: Optional[Department]) -> Optional[Department]:
    """Komórka, której kierownik odpowiada za `d` (samodzielne stanowisko /
    komórka bez aktywnego kierownika → najbliższy aktywny kierownik wyżej).
    None, gdy nikogo wyżej."""
    from services.permissions import effective_manager_dept, has_active_manager
    if d and (getattr(d, "kind", None) == "standalone" or not has_active_manager(session, d)):
        return effective_manager_dept(session, d)
    return d


def _deputy_ids(session: Session, dept: Optional[Department]) -> list[int]:
    from services.permissions import dept_deputy_ids
    if not dept:
        return []
    return sorted(dept_deputy_ids(session, dept.id))


def _unit_director_id(session: Session, dept: Optional[Department]) -> Optional[int]:
    """Kierownik CAŁEJ jednostki komórki (`Unit.manager_user_id`) — przełożony:
    adresat rezerwowy, gdy w łańcuchu nie ma nikogo innego (wtedy w komórce bez
    własnego kierownika działa od razu; akceptację wyższą wykonuje zawsze)."""
    from models import Unit
    if not dept or not getattr(dept, "unit_id", None):
        return None
    unit = session.get(Unit, dept.unit_id)
    return unit.manager_user_id if unit and unit.manager_user_id else None


def _stage_actor_ids(session: Session, node: dict,
                     dept: Optional[Department],
                     request: Optional[AccessRequest] = None) -> list[int]:
    """Id osób, które powinny działać na kroku kierowniczym (kolejność = ważność).

    - krok kierownika (wybór / akceptacja): kierownik odpowiedzialnej komórki
      i jej zastępcy, a także zastępcy SAMEJ komórki, gdy nie ma ona kierownika
      (mogą działać — `is_superior_for` z include_self),
    - akceptacja wyższa: kierownik (odpowiedzialny) komórki nadrzędnej, jego
      zastępcy oraz zastępcy samej komórki nadrzędnej — bez kierownika
      i zastępców samej komórki (wyjątek: dyrektor jednostki) i bez pracownika,
      którego wniosek dotyczy (`request`).
    Gdy nikogo takiego nie ma (komórka najwyższego poziomu, łańcuch bez
    kierownika) — dyrektor jednostki, który i tak może wykonać ten krok.
    Gdy nie ma też dyrektora (albo nikt z listy nie ma aktywnego konta) —
    superadmin (`superadmin_acts`), żeby wniosek nie utknął.
    """
    return _stage_actor_info(session, node, dept, request)[0]


# Powód rezerwy superadmina (`_stage_actor_info`) — wpływa na opis „Czeka na”.
FALLBACK_SELF = "self"      # wniosek „dla siebie”, nad pracownikiem nie ma nikogo
FALLBACK_NOBODY = "nobody"  # w strukturze nie ma żadnej osoby uprawnionej

SUPERADMIN_NOBODY_LABEL = "superadmin — brak osoby uprawnionej w strukturze"
SUPERADMIN_SELF_LABEL = ("superadmin — poza pracownikiem, którego dotyczy wniosek, nie ma "
                         "przełożonego, który mógłby go zatwierdzić")


def _stage_actor_info(session: Session, node: dict, dept: Optional[Department],
                      request: Optional[AccessRequest] = None
                      ) -> tuple[list[int], Optional[str]]:
    """(adresaci kroku jak w `_stage_actor_ids`, powód rezerwy superadmina albo
    None). Powód (`FALLBACK_SELF` / `FALLBACK_NOBODY`) oznacza, że adresatami
    są superadmini, bo w strukturze nie ma nikogo innego, kto mógłby działać."""
    ntype = node["type"]
    if ntype in MANAGER_STAGE_TYPES:
        return _manager_stage_actor_info(session, node, dept, request)
    if ntype == "higher_manager_approve":
        return _higher_actor_info(session, dept, request)
    return [], None


def _superadmin_ids(session: Session) -> list[int]:
    from services.permissions import users_with_role
    return [u.id for u in users_with_role(session, "superadmin")]


def _manager_stage_actor_info(session: Session, node: dict, dept: Optional[Department],
                              request: Optional[AccessRequest]
                              ) -> tuple[list[int], Optional[str]]:
    """Adresaci kroku kierownika komórki: kierownik odpowiedzialnej komórki i jej
    zastępcy (+ zastępcy samej komórki bez kierownika), a bez nikogo takiego —
    dyrektor jednostki; gdy nikt nie ma aktywnego konta — superadmin
    (`FALLBACK_NOBODY`).

    M1 (3.11): wniosek, który musi zatwierdzić przełożony pracownika
    (`needs_superior_approval`), w obiegu bez akceptacji wyższej, gdy nad
    pracownikiem nie ma nikogo, kto mógłby ją wykonać (łańcuch wyczerpany) —
    kierownictwo komórki nie może go wysłać (409), a przejąć nie ma kto. Krok
    wykonuje wtedy superadmin jako rezerwa (`FALLBACK_SELF`)."""
    own = dept
    resp = _responsible_dept(session, own)
    ids: list[int] = []

    def _add(uid):
        if uid and uid not in ids:
            ids.append(uid)

    if resp:
        _add(resp.manager_user_id)
        for uid in _deputy_ids(session, resp):
            _add(uid)
    if own and own is not resp:
        for uid in _deputy_ids(session, own):
            _add(uid)
    if not ids:
        _add(_unit_director_id(session, dept))
    if any(_is_active_user(session, uid) for uid in ids):
        if request is not None and _manager_stage_needs_fallback(session, node, dept, request):
            return _superadmin_ids(session), FALLBACK_SELF
        return ids, None
    return _superadmin_ids(session), FALLBACK_NOBODY


def _manager_stage_needs_fallback(session: Session, node: dict, dept: Optional[Department],
                                  request: AccessRequest) -> bool:
    """Warunek M1 z `_manager_stage_actor_info` (bez przejęcia, bez akceptacji
    wyższej w dalszej części obiegu, bez przełożonego nad pracownikiem)."""
    if not getattr(request, "worker_user_id", None) or getattr(request, "id", None) is None:
        return False
    inst = instance_of(session, request)
    if inst is None or not inst.template_snapshot:
        return False
    if effective_taker_id(session, request, dept):
        return False
    if not needs_superior_approval(session, request, dept, None, inst):
        return False
    try:
        graph = _graph_of(session, inst)
    except Exception:
        return False
    cur, seen = node.get("id"), set()
    while cur and cur not in seen:
        seen.add(cur)
        nxt = next_node(graph, cur)
        if not nxt:
            break
        if nxt["type"] == "higher_manager_approve":
            return False
        cur = nxt["id"]
    return _higher_actor_info(session, dept, request)[1] is not None


def _graph_of(session: Session, inst: WorkflowInstance) -> dict:
    graphs = session.info.setdefault("_wf_graphs", {})
    graph = graphs.get(inst.id)
    if graph is None:
        graph = json.loads(inst.template_snapshot)
        graphs[inst.id] = graph
    return graph


def _higher_actor_info(session: Session, dept: Optional[Department],
                       request: Optional[AccessRequest]
                       ) -> tuple[list[int], Optional[str]]:
    """Adresaci akceptacji wyższej: (odpowiedzialny) kierownik komórki
    nadrzędnej, jego zastępcy i zastępcy samej komórki nadrzędnej — bez
    kierownictwa samej komórki (wyjątek: dyrektor jednostki), bez pracownika
    wniosku i jego kręgu i wyłącznie osoby stojące WYŻEJ niż pracownik
    (`stands_above_worker`, 3.11). Gdy na danym poziomie nie ma nikogo
    aktywnego — szukamy wyżej (N4); po wyczerpaniu łańcucha — dyrektor
    jednostki; dopiero potem rezerwa superadmina."""
    worker_id = getattr(request, "worker_user_id", None) if request is not None else None
    director = _unit_director_id(session, dept)
    own_circle: set[int] = set()
    worker_circle: set[int] = set()
    if dept is not None:
        own_circle = set(_deputy_ids(session, dept))
        if dept.manager_user_id:
            own_circle.add(dept.manager_user_id)
    if request is not None:
        worker_circle = worker_lead_circle(session, request, dept)
    ids: list[int] = []
    dropped_for_worker = False

    def _consider(uid) -> None:
        nonlocal dropped_for_worker
        if not uid or uid in ids:
            return
        if uid == worker_id:
            dropped_for_worker = True
            return
        if uid in worker_circle and uid != director:
            dropped_for_worker = True
            return
        if uid in own_circle and uid != director:
            return
        if worker_id and not stands_above_worker(session, session.get(User, uid), request):
            dropped_for_worker = True
            return
        ids.append(uid)

    own = session.get(Department, dept.parent_dept_id) if dept and dept.parent_dept_id else None
    seen: set[int] = set()
    while own is not None and own.id not in seen:
        seen.add(own.id)
        resp = _responsible_dept(session, own)
        if resp:
            _consider(resp.manager_user_id)
            for uid in _deputy_ids(session, resp):
                _consider(uid)
        if own is not resp:
            for uid in _deputy_ids(session, own):
                _consider(uid)
        if any(_is_active_user(session, uid) for uid in ids):
            return ids, None
        top = resp or own
        own = session.get(Department, top.parent_dept_id) if top.parent_dept_id else None
    if director and _is_active_user(session, director):
        _consider(director)
    if any(_is_active_user(session, uid) for uid in ids):
        return ids, None
    # Nikt w strukturze nie może wykonać kroku — rezerwa superadmina. Wniosek
    # dla osoby, nad którą nie ma nikogo (np. dyrektor jednostki albo kierownik
    # najwyższej komórki), ma osobny opis.
    reason = FALLBACK_NOBODY
    if worker_id and (dropped_for_worker or director == worker_id or worker_circle):
        reason = FALLBACK_SELF
    return _superadmin_ids(session), reason


def _is_active_user(session: Session, user_id: Optional[int]) -> bool:
    u = session.get(User, user_id) if user_id else None
    return bool(u and u.is_active)


def _addressee_for_node(session: Session, node: dict, request: AccessRequest,
                        dept: Optional[Department],
                        exclude_ids: Any = ()) -> list[str]:
    """Adresy e-mail osób, które trzeba powiadomić o wejściu w dany węzeł.

    Spójnie z `waiting_for_label` i `can_act` — patrz `_stage_actor_ids`.
    `exclude_ids` — osoby pomijane (np. sprawca przejścia, który sam wysłał
    wniosek na ten etap). Puste, jeśli nie potrafimy znaleźć adresata."""
    if node["type"] == "it_execute":
        # Realizacja IT: powiadamiamy WYŁĄCZNIE skrzynkę helpdesku
        # (patrz `_notify_helpdesk`) — bez imiennych maili do pracowników IT,
        # bo zgłoszenie zakłada się w systemie helpdesku, nie u poszczególnych osób.
        return []
    skip = {x for x in (exclude_ids or ()) if x}
    emails: list[str] = []
    # Etap kierownika komórki przejęty przez przełożonego (przejęcie wciąż
    # ważne) — krok wykona wyłącznie przejmujący; kierownik komórki i zastępcy
    # nie mogą działać, więc nie dostają „czeka na Ciebie”.
    taker_id = (effective_taker_id(session, request, dept)
                if node["type"] in MANAGER_STAGE_TYPES
                and is_manager_stage(session, node["type"], dept) else None)
    candidates = [taker_id] if taker_id else _stage_actor_ids(session, node, dept, request)
    for uid in candidates:
        if uid in skip:
            continue
        u = session.get(User, uid)
        if u and u.is_active and u.email and u.email not in emails:
            emails.append(u.email)
    return emails


def _person_name(session: Session, user_id: Optional[int]) -> Optional[str]:
    if not user_id:
        return None
    u = session.get(User, user_id)
    return (u.full_name or u.username) if u else None


def waiting_for_label(session: Session, node: Optional[dict], request: AccessRequest,
                      dept: Optional[Department]) -> Optional[str]:
    """Krótki opis, KTO ma teraz działać na wniosku (v3.1 — „Czeka na: …”).

    Odpowiada logice adresata powiadomień: samodzielne stanowisko / komórka bez
    kierownika → najbliższy kierownik wyżej (albo zastępca samej komórki);
    akceptacja wyższa → kierownik komórki nadrzędnej; brak kogokolwiek →
    dyrektor jednostki; realizacja → przypisany pracownik IT albo Biuro Informatyki.
    """
    if not node:
        return None
    from models import Unit
    ntype = node.get("type")
    # Wniosek przejęty przez przełożonego — krok kierowniczy wykona przejmujący
    # (o ile przejęcie jest wciąż ważne).
    taker_id = (effective_taker_id(session, request, dept)
                if ntype in MANAGER_STAGE_TYPES else None)
    if taker_id:
        who = request.taken_over_by_name or _person_name(session, taker_id)
        if who:
            return f"{who} (przełożony — przejął wniosek)"
    if ntype == "higher_manager_approve":
        return _higher_waiting_label(session, node, request, dept)
    if ntype in ("manager_approve", "select_permissions"):
        fallback = _stage_actor_info(session, node, dept, request)[1]
        if fallback == FALLBACK_SELF:
            return SUPERADMIN_SELF_LABEL
        if fallback:
            return SUPERADMIN_NOBODY_LABEL
        own = dept
        resp = _responsible_dept(session, own)
        # Komórka bez (własnego) kierownika, ale z zastępcą — to on jest
        # najbliżej i dostaje powiadomienie (kierownik wyżej też może działać).
        if own is not None and own is not resp:
            dep_names = [n for n in (_person_name(session, uid)
                                     for uid in _deputy_ids(session, own)) if n]
            if dep_names:
                return f"{', '.join(dep_names)} (zastępca kierownika {own.name})"
        name = _person_name(session, resp.manager_user_id) if resp else None
        if name:
            return f"{name} (kierownik {resp.name})"
        director = _unit_director_id(session, dept)
        dname = _person_name(session, director)
        if dname:
            unit = session.get(Unit, dept.unit_id) if dept else None
            return f"dyrektor jednostki: {dname}" + (f" ({unit.name})" if unit else "")
        return "kierownik komórki (nieprzypisany)"
    if ntype == "it_execute":
        name = _person_name(session, getattr(request, "assigned_to_user_id", None))
        return f"IT: {name}" if name else "Biuro Informatyki (IT)"
    return node.get("label") or ntype


def _higher_waiting_label(session: Session, node: dict, request: AccessRequest,
                          dept: Optional[Department]) -> str:
    """„Czeka na” przy akceptacji wyższej — spójnie z adresatami powiadomień
    (`_stage_actor_info`): bez kierownika i zastępców samej komórki (poza
    dyrektorem jednostki) i bez pracownika, którego wniosek dotyczy."""
    from models import Unit
    ids, fallback = _stage_actor_info(session, node, dept, request)
    if fallback == FALLBACK_SELF:
        return SUPERADMIN_SELF_LABEL
    if fallback:
        return SUPERADMIN_NOBODY_LABEL
    if not ids:
        return "kierownik nadrzędny (nieprzypisany)"
    parent = (session.get(Department, dept.parent_dept_id)
              if dept and dept.parent_dept_id else None)
    resp = _responsible_dept(session, parent)
    if resp and resp.manager_user_id in ids:
        return f"kierownik nadrzędny: {_person_name(session, resp.manager_user_id)} ({resp.name})"
    if parent is not None and parent is not resp:
        dep_names = [n for n in (_person_name(session, uid)
                                 for uid in _deputy_ids(session, parent) if uid in ids) if n]
        if dep_names:
            return (f"kierownik nadrzędny: {', '.join(dep_names)} "
                    f"(zastępca kierownika {parent.name})")
    director = _unit_director_id(session, dept)
    if ids == [director]:
        unit = session.get(Unit, dept.unit_id) if dept else None
        return (f"dyrektor jednostki: {_person_name(session, director)}"
                + (f" ({unit.name})" if unit else ""))
    names = [n for n in (_person_name(session, uid) for uid in ids) if n]
    return "kierownik nadrzędny: " + ", ".join(names)


def current_step_since(session: Session, instance: WorkflowInstance) -> Optional[datetime]:
    """Kiedy wniosek wszedł w bieżący węzeł = data ostatniego kroku obiegu."""
    from models import WorkflowStep
    last = session.exec(
        select(WorkflowStep)
        .where(WorkflowStep.instance_id == instance.id)
        .order_by(WorkflowStep.step_index.desc())
    ).first()
    return last.created_at if last else instance.created_at


def _selector_step(session: Session, request: AccessRequest):
    """Ostatni krok „wybór uprawnień" — czyli kierownik, który zawnioskował
    o konkretne uprawnienia. To on jest właściwym adresatem powiadomień
    o losach wniosku (a nie kadrowa, która tylko zgłosiła zatrudnienie).
    """
    from models import WorkflowInstance, WorkflowStep, WorkflowStepAction
    inst = session.exec(
        select(WorkflowInstance).where(WorkflowInstance.request_id == request.id)
    ).first()
    if not inst:
        return None
    return session.exec(
        select(WorkflowStep)
        .where(WorkflowStep.instance_id == inst.id)
        .where(WorkflowStep.action == WorkflowStepAction.select)
        .order_by(WorkflowStep.step_index.desc())
    ).first()


def _notify_helpdesk(session: Session, request: AccessRequest,
                     actor_user: Optional[User] = None) -> None:
    """Zgłoszenie na skrzynkę helpdesku IT — wniosek wszedł w krok realizacji."""
    try:
        step = _selector_step(session, request)
        manager_name = (step.actor_name if step and step.actor_name
                        else (request.created_by_name or ""))
        # Nadawca = WNIOSKODAWCA (osoba, która wystąpiła o uprawnienia — kierownik
        # z kroku wyboru), a nie ten, kto ostatnio przesunął wniosek. Kolejno:
        # aktor kroku wyboru → twórca wniosku → w ostateczności aktor akcji.
        s_name = s_email = None
        applicant = None
        if step and step.actor_user_id:
            applicant = session.get(User, step.actor_user_id)
        if not (applicant and applicant.email) and request.created_by_id:
            applicant = session.get(User, request.created_by_id)
        s_name, s_email = _actor_sender(applicant)
        if not s_email:
            s_name, s_email = _actor_sender(actor_user)

        from services.email_alerts import notify_helpdesk_new_request
        defer(session, notify_helpdesk_new_request, **{
                "request_id": request.id,
                "worker_name": request.worker_name,
                "manager_name": manager_name,
                "kind": getattr(request, "kind", "grant") or "grant",
                "from_name": s_name, "from_email": s_email,
            })
    except Exception as exc:
        _log.warning("Powiadomienie helpdesku nie zostało wysłane: %s", exc)


def _notify_stage(session: Session, request: AccessRequest, node: dict,
                  dept: Optional[Department],
                  actor_user: Optional[User] = None,
                  exclude_ids: Any = ()) -> None:
    """Powiadamia adresata w tle o wejściu wniosku w nowy węzeł.

    Nadawcą powiadomienia jest `actor_user` — osoba, której akcja przesunęła
    wniosek do tego etapu (np. kierownik, który zaakceptował). To ona figuruje
    jako „od kogo" w skrzynce adresata, ale sama maila NIE dostaje (nie
    powiadamiamy nikogo o kroku, który sam właśnie wysłał).
    `exclude_ids` — dodatkowe osoby do pominięcia (np. już powiadomione).
    """
    try:
        # Wejście w realizację IT → dodatkowo zgłoszenie na helpdesk.
        if node.get("type") == "it_execute":
            _notify_helpdesk(session, request, actor_user)

        skip = set(exclude_ids or ())
        if actor_user is not None and actor_user.id:
            skip.add(actor_user.id)
        emails = _addressee_for_node(session, node, request, dept, skip)
        if not emails:
            fb_ids, fallback = (_stage_actor_info(session, node, dept, request)
                                if node.get("type") in STRUCTURE_SENSITIVE_TYPES
                                else ([], None))
            if fallback and not any(getattr(session.get(User, uid), "email", None)
                                    for uid in fb_ids):
                # Rezerwa superadmina bez adresu e-mail — wniosek czeka na
                # superadmina, ale nikt o tym nie wie. Ślad w logu dla administratora.
                _log.warning(
                    "Wniosek #%s czeka na superadmina (brak osoby uprawnionej "
                    "w strukturze), ale żadne konto superadmina nie ma adresu "
                    "e-mail — powiadomienie nie zostało wysłane.", request.id)
            return
        s_name, s_email = _actor_sender(actor_user)
        from services.email_alerts import notify_workflow_stage, request_view_url
        from services.permissions import users_with_role
        # Superadmin nie ma zakładek obsługi wniosków — link do widoku wniosku.
        sa_emails = {u.email for u in users_with_role(session, "superadmin") if u.email}
        for e in emails:
            extra = {"url": request_view_url(request.id)} if e in sa_emails else {}
            defer(session, notify_workflow_stage, **{
                    "to_address": e,
                    "request_id": request.id,
                    "worker_name": request.worker_name,
                    "dept_name": dept.name if dept else "",
                    "stage_label": node.get("label") or node["type"],
                    "node_type": node["type"],
                    "from_name": s_name, "from_email": s_email,
                    **extra,
                })
    except Exception as exc:
        _log.warning("Powiadomienie o etapie obiegu nie zostało wysłane: %s", exc)


def _notify_request_completed(session: Session, request: AccessRequest,
                              actor_user: Optional[User] = None) -> None:
    """Wniosek zrealizowany — powiadom KIEROWNIKA, który wybierał uprawnienia
    (wystąpił o konkretne uprawnienia i czeka na ich nadanie), oraz TWÓRCĘ
    zgłoszenia (zwykle kadry), jeśli to inna osoba — kadry muszą wiedzieć, że
    pracownik ma już dostęp. Gdy kroku wyboru nie było, adresatem jest tylko
    twórca. Nadawcą jest osoba z IT, która zrealizowała wniosek (`actor_user`);
    ona sama maila nie dostaje."""
    try:
        targets: list[int] = []
        step = _selector_step(session, request)
        for uid in ((step.actor_user_id if step else None), request.created_by_id):
            if uid and uid not in targets:
                targets.append(uid)
        users = []
        for uid in targets:
            if actor_user is not None and uid == actor_user.id:
                continue   # realizujący sam jest wnioskodawcą
            u = session.get(User, uid)
            if u and u.is_active and u.email and all(x.email != u.email for x in users):
                users.append(u)
        if not users:
            return
        s_name, s_email = _actor_sender(actor_user)
        # Lista pozycji ODMÓWIONYCH — wnioskodawca ma wiedzieć, czego NIE nadano
        # i dlaczego. Zbieramy tylko pozycje nadania (odebrania nie dotyczą).
        from models import PermissionSystem, SystemPermission
        denied_lines: list[str] = []
        for it in session.exec(
            select(RequestItem).where(RequestItem.request_id == request.id)
        ).all():
            if not getattr(it, "denied", False):
                continue
            if (getattr(it, "kind", "grant") or "grant") == "revoke":
                continue
            perm = session.get(SystemPermission, it.permission_id)
            sysrow = session.get(PermissionSystem, it.system_id)
            label = (f"{sysrow.name if sysrow else it.system_id} — "
                     f"{perm.permission_name if perm else it.permission_id}")
            if getattr(it, "deny_comment", None):
                label += f" (powód: {it.deny_comment})"
            denied_lines.append(label)
        from services.email_alerts import notify_request_completed
        from services.permissions import user_is_hr
        for u in users:
            defer(session, notify_request_completed, **{
                    "requester_email": u.email,
                    "request_id": request.id,
                    "worker_name": request.worker_name,
                    "from_name": s_name, "from_email": s_email,
                    "denied_lines": denied_lines,
                    # Link w mailu: kierownik → „Moje wnioski”, kadry → Kartoteka.
                    "requester_is_manager": has_role(u, "manager"),
                    "requester_is_hr": user_is_hr(session, u),
                })
    except Exception as exc:
        _log.warning("Powiadomienie o zakończeniu wniosku nie wysłane: %s", exc)


def _notify_request_rejected(session: Session, request: AccessRequest,
                             actor_user: Optional[User], comment: Optional[str],
                             extra_ids: Any = ()) -> None:
    """Wniosek odrzucony — powiadom twórcę zgłoszenia (zwykle kadry) oraz
    kierownika, który wybierał uprawnienia (jeśli to inna osoba niż odrzucający).
    `extra_ids` — dodatkowi adresaci (np. kierownik komórki i jego zastępcy,
    gdy wniosek odrzucił na etapie kierownika przełożony)."""
    try:
        targets: list[int] = []
        if request.created_by_id:
            targets.append(request.created_by_id)
        step = _selector_step(session, request)
        if step and step.actor_user_id and step.actor_user_id not in targets:
            targets.append(step.actor_user_id)
        for uid in extra_ids or ():
            if uid and uid not in targets:
                targets.append(uid)
        from services.email_alerts import notify_request_rejected
        from services.permissions import user_is_hr
        for uid in targets:
            if actor_user and uid == actor_user.id:
                continue   # odrzucający nie dostaje maila o własnej decyzji
            u = session.get(User, uid)
            if not u or not u.is_active or not u.email:
                continue
            defer(session, notify_request_rejected, **{
                    "requester_email": u.email,
                    "request_id": request.id,
                    "worker_name": request.worker_name,
                    "comment": comment or "",
                    "requester_is_manager": has_role(u, "manager"),
                    "requester_is_hr": user_is_hr(session, u),
                })
    except Exception as exc:
        _log.warning("Powiadomienie o odrzuceniu wniosku nie wysłane: %s", exc)


def _audit_request_event(session: Session, request: AccessRequest, action: str,
                         actor_user: Optional[User], **extra: Any) -> None:
    """Zdarzenie domenowe wniosku w dzienniku audytu (`request.completed`,
    `request.rejected`) — w tej samej transakcji co zmiana stanu."""
    try:
        from services.audit import record_event
        record_event(
            session, action=action,
            user_id=actor_user.id if actor_user else None,
            username=actor_user.username if actor_user else None,
            target_type="access_request", target_id=request.id,
            details={"kind": getattr(request, "kind", None) or "grant",
                     "worker_user_id": getattr(request, "worker_user_id", None),
                     "department_id": getattr(request, "department_id", None),
                     **extra},
            commit=False,
        )
    except Exception:
        _log.exception("Nie udało się zapisać zdarzenia %s wniosku #%s w dzienniku audytu",
                       action, getattr(request, "id", None))


EXECUTOR_DID_MANAGER_STEP_MSG = (
    "Wykonałeś(-aś) w tym wniosku krok etapu kierownika (wybór, akceptację albo "
    "akceptację wyższą) — realizację w IT musi wykonać inna osoba z IT.")


def execute_blocked_reason(session: Session, request: AccessRequest,
                           user: User) -> Optional[str]:
    """Ś11 (3.11): osoba z IT, która wykonała w tym wniosku krok etapu
    kierownika (wybór / akceptacja kierownika / akceptacja wyższa — także
    automatyczny), nie realizuje go w IT — chyba że w systemie jest tylko jedna
    aktywna osoba z rolą it_staff. Realizacja wniosku „dla siebie” (krok
    kierownika wykonał ktoś inny) jest dozwolona. None — brak przeszkody."""
    if user is None or not has_role(user, "it_staff"):
        return None
    inst = instance_of(session, request) if getattr(request, "id", None) else None
    if inst is None or inst.id is None:
        return None
    from sqlmodel import col
    did = session.exec(
        select(WorkflowStep.id)
        .where(WorkflowStep.instance_id == inst.id)
        .where(WorkflowStep.actor_user_id == user.id)
        .where(col(WorkflowStep.node_type).in_(list(STRUCTURE_SENSITIVE_TYPES)))
        .where(col(WorkflowStep.action).in_([WorkflowStepAction.select,
                                             WorkflowStepAction.approve]))
    ).first() is not None
    if not did:
        return None
    from services.permissions import users_with_role
    if len(users_with_role(session, "it_staff")) <= 1:
        return None
    return EXECUTOR_DID_MANAGER_STEP_MSG


def superadmin_emergency(session: Session, node: Optional[dict], request: AccessRequest,
                         dept: Any = _UNSET) -> bool:
    """Czy bieżący krok czeka na superadmina jako rezerwę (brak osoby uprawnionej
    w strukturze albo nikogo nad pracownikiem)."""
    if not node or node.get("type") not in STRUCTURE_SENSITIVE_TYPES:
        return False
    if dept is _UNSET:
        dept = session.get(Department, request.department_id) if request.department_id else None
    if node.get("type") in MANAGER_STAGE_TYPES and effective_taker_id(session, request, dept):
        return False
    return bool(_stage_actor_info(session, node, dept, request)[1])


def _sync_request_status(request: AccessRequest, instance: WorkflowInstance) -> None:
    """Mapuje status instancji na RequestStatus, żeby stare dashboardy dalej
    pokazywały coś sensownego. Nowe widoki czytają current_node_id.
    """
    # Kopia typu bieżącego węzła — filtr widoczności listy w SQL.
    request.current_node_type = None
    if instance.status == WorkflowInstanceStatus.completed:
        request.status = RequestStatus.completed
        if not request.completed_at:
            request.completed_at = datetime.utcnow()
    elif instance.status == WorkflowInstanceStatus.rejected:
        request.status = RequestStatus.rejected
        if not request.rejected_at:
            request.rejected_at = datetime.utcnow()
    else:
        current_type = None
        try:
            graph = json.loads(instance.template_snapshot)
            n = find_node(graph, instance.current_node_id)
            current_type = n["type"] if n else None
        except Exception:
            # Uszkodzony graf instancji — status ustawiamy zachowawczo, ale
            # administrator musi to zobaczyć w logu.
            _log.exception("Nie udało się odczytać bieżącego węzła instancji %s "
                           "(wniosek #%s) — uszkodzony graf obiegu.",
                           instance.id, getattr(request, "id", None))
        request.current_node_type = current_type
        if current_type == "select_permissions":
            request.status = RequestStatus.pending_selection
        elif current_type == "it_execute":
            request.status = RequestStatus.pending_it
        else:
            request.status = RequestStatus.pending_manager


# ---------------------------------------------------------------------------
# Akcja użytkownika na aktualnym węźle
# ---------------------------------------------------------------------------

def validate_action(
    session: Session,
    instance: WorkflowInstance,
    request: AccessRequest,
    user: User,
    action: str,
) -> tuple[dict, Optional[Department]]:
    """Sprawdza (BEZ żadnych zmian w bazie), czy `user` może wykonać `action`
    na bieżącym węźle: stan instancji, węzeł, `can_act`, dozwolona akcja i wymóg
    obiegu papierowego. Zwraca (węzeł, komórka) albo rzuca HTTPException.

    Router woła to PRZED zapisem pozycji / kont pracowników, żeby odmowa (403/400)
    nie zostawiała w bazie częściowych zmian; `execute_action` woła to ponownie.
    """
    if instance.status != WorkflowInstanceStatus.active:
        raise HTTPException(400, f"Instancja obiegu jest w stanie {instance.status.value} — brak akcji.")

    graph = json.loads(instance.template_snapshot)
    node = find_node(graph, instance.current_node_id) if instance.current_node_id else None
    if not node:
        raise HTTPException(400, "Instancja nie ma aktualnego węzła.")
    ntype = node["type"]

    dept = session.get(Department, request.department_id) if request.department_id else None
    allowed, reason = can_act(node, request, dept, user, session)
    if not allowed:
        raise HTTPException(403, reason)

    # Walidacja akcji → typ węzła
    valid = {
        "start":                   set(),  # nie da się „ręcznie" — auto_advance
        "select_permissions":      {"select", "reject"},
        "manager_approve":         {"approve", "reject"},
        "higher_manager_approve":  {"approve", "reject"},
        "it_execute":              {"execute", "reject"},
        "end":                     set(),
    }.get(ntype, set())
    if action not in valid:
        raise HTTPException(400, f"Akcja '{action}' nie jest dozwolona na węźle '{ntype}'. "
                                 f"Dozwolone: {', '.join(sorted(valid)) or 'brak (auto)'}")

    return node, dept


def execute_action(
    session: Session,
    instance: WorkflowInstance,
    request: AccessRequest,
    user: User,
    action: str,
    payload: Any = None,
    comment: Optional[str] = None,
) -> WorkflowInstance:
    """Waliduje uprawnienia, zapisuje krok, przechodzi do kolejnego węzła.

    action ∈ {"approve", "reject", "select", "execute"}
    """
    node, dept = validate_action(session, instance, request, user, action)

    action_enum = {
        "approve": WorkflowStepAction.approve,
        "reject":  WorkflowStepAction.reject,
        "select":  WorkflowStepAction.select,
        "execute": WorkflowStepAction.execute,
    }[action]
    # Superadmin działa w obiegu wyłącznie jako rezerwa — krok jest oznaczony
    # w podpisanym payloadzie jako awaryjny.
    if has_role(user, "superadmin"):
        payload = {**(payload if isinstance(payload, dict) else
                      ({} if payload is None else {"value": payload})),
                   "superadmin_emergency": True}

    _record_step(session, instance, node,
                 action=action_enum, actor_user=user, payload=payload, comment=comment)

    if action == "reject":
        # Odrzucenie na etapie kierownika komórki przez przełożonego (po
        # przejęciu) — kierownik komórki i jego zastępcy też muszą o tym wiedzieć
        # (wniosek był „u nich”). Liczymy PRZED zmianą statusu instancji.
        extra: list[int] = []
        if is_manager_stage(session, node["type"], dept):
            from services.permissions import is_department_manager_or_deputy
            if not is_department_manager_or_deputy(session, user, dept):
                extra = ([dept.manager_user_id] if dept.manager_user_id else []) \
                    + _deputy_ids(session, dept)
        instance.status = WorkflowInstanceStatus.rejected
        instance.completed_at = datetime.utcnow()
        session.add(instance)
        _sync_request_status(request, instance)
        _audit_request_event(session, request, "request.rejected", user,
                             node_type=node["type"])
        _notify_request_rejected(session, request, user, comment, extra_ids=extra)
        return instance

    # Dodatkowa logika: przy select_permissions zapisujemy wybrane item_ids
    # do payloadu; router routera „applies" je do RequestItem (poza silnikiem).
    # Przy manager_approve/higher_manager_approve/it_execute — nic więcej, silnik idzie dalej.

    advance(session, instance, request, actor_user=user)
    return instance


# ---------------------------------------------------------------------------
# Serializacja stanu do frontendu
# ---------------------------------------------------------------------------

def serialize_instance(session: Session, instance: WorkflowInstance) -> dict:
    graph = json.loads(instance.template_snapshot)
    current = find_node(graph, instance.current_node_id) if instance.current_node_id else None
    steps = session.exec(
        select(WorkflowStep)
        .where(WorkflowStep.instance_id == instance.id)
        .order_by(WorkflowStep.step_index.asc())
    ).all()

    return {
        "instance_id": instance.id,
        "request_id": instance.request_id,
        "template_id": instance.template_id,
        "template_version": instance.template_version,
        "status": instance.status.value if hasattr(instance.status, "value") else instance.status,
        "current_node_id": instance.current_node_id,
        "current_node": current,
        "steps": [
            {
                "step_index": s.step_index,
                "node_id": s.node_id,
                "node_type": s.node_type,
                "action": s.action.value if hasattr(s.action, "value") else s.action,
                "actor_user_id": s.actor_user_id,
                "actor_name": s.actor_name,
                "payload": s.payload,
                "comment": s.comment,
                "signature": s.signature,
                "created_at": s.created_at,
            } for s in steps
        ],
        "created_at": instance.created_at,
        "completed_at": instance.completed_at,
    }
