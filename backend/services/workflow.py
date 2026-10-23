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

def _sign(prev_signature: Optional[str], step_data: dict) -> str:
    """Podpis łańcuchowy: sha256(secret + prev_sig + kanoniczny_step_json).

    Nie jest to podpis kwalifikowany, ale wykrywa manipulację historią
    (wstawianie / modyfikacja kroków). PIN podpisu użytkownika dodamy
    w kolejnej iteracji jako dodatkowy element hashowany.
    """
    payload = json.dumps(step_data, sort_keys=True, ensure_ascii=False, default=str)
    material = f"{_SIGN_SECRET}|{prev_signature or ''}|{payload}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


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
        expected = _sign(prev, {
            "step_index": s.step_index,
            "node_id": s.node_id,
            "node_type": s.node_type,
            "action": s.action.value if hasattr(s.action, "value") else s.action,
            "actor_user_id": s.actor_user_id,
            "payload": s.payload,
            "comment": s.comment,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        })
        if s.signature != expected or s.prev_signature != prev:
            return False
        prev = s.signature
    return True


# ---------------------------------------------------------------------------
# Ocena skip_if — na razie: pojedyncza flaga „skip_if_not_required" dla
# węzła higher_manager_approve czyta Department.requires_higher_approval.
# Rozszerzenia (np. skip_if_asset_not_personal_data) dokładamy tu.
# ---------------------------------------------------------------------------

def should_skip(node: dict, request: AccessRequest, dept: Optional[Department]) -> bool:
    props = node.get("props") or {}
    if node["type"] == "higher_manager_approve":
        if props.get("skip_if_not_required", True):
            if not dept or not dept.requires_higher_approval:
                return True
    return False


def landing_node_type(
    session: Session,
    instance: WorkflowInstance,
    request: AccessRequest,
    action: str,
) -> Optional[str]:
    """Typ węzła, na którym zatrzyma się obieg PO wykonaniu `action` z bieżącego
    węzła — bez mutacji stanu (podgląd `advance`).

    `reject` nie posuwa obiegu naprzód → None. Dla `select`/`approve` idziemy
    krawędziami od bieżącego węzła, pomijając auto-skip (`should_skip`) aż do
    pierwszego węzła interaktywnego albo `end`. Dzięki temu wiadomo z góry, czy
    ten ruch kieruje wniosek do realizacji IT (`it_execute`).
    """
    if action == "reject" or not instance.current_node_id:
        return None
    graph = json.loads(instance.template_snapshot)
    dept = session.get(Department, request.department_id) if request.department_id else None

    node_id = instance.current_node_id
    for _ in range(100):
        nxt = next_node(graph, node_id)
        if not nxt:
            return None
        node_id = nxt["id"]
        if nxt["type"] == "end":
            return "end"
        if should_skip(nxt, request, dept):
            continue
        return nxt["type"]
    return None


def grants_permissions(session: Session, request: AccessRequest) -> bool:
    """Czy wniosek NADAJE co najmniej jedno uprawnienie (pozycja `kind='grant'`).

    Czyste odebranie/ustanie stosunku pracy nie nadaje niczego → oświadczenie
    wnioskującego nie ma zastosowania.
    """
    items = session.exec(
        select(RequestItem).where(RequestItem.request_id == request.id)
    ).all()
    return any((getattr(i, "kind", "grant") or "grant") == "grant" for i in items)


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

    Widzą go: superadmin, twórca wniosku (np. kadry), kierownik komórki i jego
    zastępcy, osoba, która wniosek przejęła, oraz przełożeni (kierownik / zastępca
    komórki wyżej w strukturze, dyrektor jednostki) — ci ostatni tylko do odczytu,
    dopóki wniosku nie przejmą.
    """
    from services.permissions import is_department_manager_or_deputy, is_superior_for

    if dept is _UNSET:
        dept = session.get(Department, request.department_id) if request.department_id else None
    if node_type is _UNSET:
        node = current_node_of(session, request)
        node_type = node.get("type") if node else None
    if not is_manager_stage(session, node_type, dept):
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
    liczył już tylko widoczne wiersze. None — nic nie trzeba wycinać.

    Ukryty jest wniosek, który stoi na etapie kierownika komórki z własnym,
    aktywnym kierownikiem (`AccessRequest.current_node_type`), nie został
    złożony przez `user`, a jego komórka leży poza „kręgiem” `user`
    (`superior_dept_ids`: komórki, którymi kieruje lub jest zastępcą, ich
    poddrzewo i komórki jednostki, którą kieruje).

    Siatka bezpieczeństwa: wniosek W TOKU z pustym `current_node_type` (kolumna
    niewypełniona — np. nieudany backfill po migracji) w takiej komórce też jest
    ukryty. Pusty typ przepuszczamy tylko dla wniosków zakończonych/odrzuconych
    (silnik zeruje wtedy kolumnę). Lepiej chwilowo nie pokazać wniosku na liście,
    niż ujawnić wersję roboczą kierownika; podgląd pojedynczego wniosku i tak
    liczy regułę z instancji obiegu (`manager_stage_visibility`)."""
    from sqlalchemy import and_, or_
    from sqlmodel import col
    from services.permissions import superior_dept_ids
    if has_role(user, "superadmin"):
        return None
    staged = session.exec(
        select(Department).join(User, User.id == Department.manager_user_id)
        .where(User.is_active == True)  # noqa: E712
    ).all()
    own_mgr = {d.id for d in staged if getattr(d, "kind", None) != "standalone"}
    hidden = sorted(own_mgr - set(superior_dept_ids(session, user)))
    if not hidden:
        return None
    return or_(
        and_(col(AccessRequest.current_node_type).is_(None),
             col(AccessRequest.status).in_([RequestStatus.completed, RequestStatus.rejected])),
        col(AccessRequest.current_node_type).notin_(list(MANAGER_STAGE_TYPES)),
        col(AccessRequest.department_id).notin_(hidden),
        col(AccessRequest.created_by_id) == user.id,
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
    """Czy `user` może oddać przejęcie („Oddaj”) — przejmujący albo superadmin,
    tylko póki wniosek stoi na etapie kierownika komórki."""
    if not getattr(request, "taken_over_by_id", None):
        return False
    if not (request.taken_over_by_id == user.id or has_role(user, "superadmin")):
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
    for uid in _stage_actor_ids(session, node, dept):
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


def release_take_overs_of(session: Session, user_id: Optional[int], note: str) -> int:
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

def can_act(node: dict, request: AccessRequest, dept: Optional[Department],
            user: User, session: Session) -> tuple[bool, str]:
    """Zwraca (dozwolone, powód-jeśli-nie).

    Wariant A (czysty rozdział obowiązków): działać w obiegu mogą wyłącznie role
    OPERACYJNE (kierownik / zastępca / pracownik IT). Administrator KONFIGURUJE
    system i NIE działa w obiegu — jeśli ma realizować/akceptować, dostaje
    właściwą rolę operacyjną. Superadmin pozostaje break-glass (może wszystko).

    Zastępcy (DepartmentDeputy) traktowani na równi z głównym kierownikiem
    komórki — mogą wykonać krok `select_permissions` / `manager_approve`
    dla swojej komórki oraz `higher_manager_approve` gdy są zastępcą
    kierownika wydziału nadrzędnego.
    """
    from services.permissions import (
        is_department_manager_or_deputy, effective_manager_dept, is_superior_for,
    )

    if has_role(user, "superadmin"):
        return True, ""

    ntype = node["type"]

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
        # Kierownik (lub zastępca) SAMEJ komórki nie zatwierdza akceptacji
        # wyższej wniosku własnej komórki — także wtedy, gdy jest jednocześnie
        # kierownikiem / zastępcą komórki nadrzędnej (inaczej zatwierdziłby
        # wniosek „sam u siebie” dwa razy). Jedyny wyjątek: dyrektor jednostki
        # (świadoma decyzja — nad nim nie ma już nikogo w strukturze).
        if (is_department_manager_or_deputy(session, user, dept)
                and _unit_director_id(session, dept) != user.id):
            return False, ("Kierownik komórki i jego zastępcy nie zatwierdzają akceptacji "
                           "wyższej wniosku własnej komórki — zrobi to przełożony.")
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
    """
    graph = json.loads(instance.template_snapshot)
    dept = session.get(Department, request.department_id) if request.department_id else None

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
            _notify_request_completed(session, request, actor_user)
            return

        if should_skip(nxt, request, dept):
            _record_step(session, instance, nxt,
                         action=WorkflowStepAction.auto_skip, actor_user=None,
                         comment="Warunek pominięcia spełniony")
            continue  # przejdź do kolejnego

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
                     dept: Optional[Department]) -> list[int]:
    """Id osób, które powinny działać na kroku kierowniczym (kolejność = ważność).

    - krok kierownika (wybór / akceptacja): kierownik odpowiedzialnej komórki
      i jej zastępcy, a także zastępcy SAMEJ komórki, gdy nie ma ona kierownika
      (mogą działać — `is_superior_for` z include_self),
    - akceptacja wyższa: kierownik (odpowiedzialny) komórki nadrzędnej, jego
      zastępcy oraz zastępcy samej komórki nadrzędnej.
    Gdy nikogo takiego nie ma (komórka najwyższego poziomu, łańcuch bez
    kierownika) — dyrektor jednostki, który i tak może wykonać ten krok.
    """
    ntype = node["type"]
    if ntype in ("manager_approve", "select_permissions"):
        own = dept
    elif ntype == "higher_manager_approve":
        own = session.get(Department, dept.parent_dept_id) if dept and dept.parent_dept_id else None
    else:
        return []

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
    director = _unit_director_id(session, dept)
    if ntype == "higher_manager_approve" and dept is not None:
        # Kierownik / zastępca samej komórki nie wykona akceptacji wyższej
        # (patrz `can_act`) — nie wysyłamy mu „czeka na Ciebie”, nawet gdy jest
        # też zastępcą komórki nadrzędnej. Wyjątek: dyrektor jednostki.
        own_circle = set(_deputy_ids(session, dept))
        if dept.manager_user_id:
            own_circle.add(dept.manager_user_id)
        ids = [uid for uid in ids if uid not in own_circle or uid == director]
    if not ids:
        _add(director)
    return ids


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
    for uid in _stage_actor_ids(session, node, dept):
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
    if ntype in ("manager_approve", "select_permissions", "higher_manager_approve"):
        higher = ntype == "higher_manager_approve"
        own = (session.get(Department, dept.parent_dept_id)
               if higher and dept and dept.parent_dept_id else (None if higher else dept))
        resp = _responsible_dept(session, own)
        # Komórka bez (własnego) kierownika, ale z zastępcą — to on jest
        # najbliżej i dostaje powiadomienie (kierownik wyżej też może działać).
        if own is not None and own is not resp:
            dep_names = [n for n in (_person_name(session, uid)
                                     for uid in _deputy_ids(session, own)) if n]
            if dep_names:
                return (("kierownik nadrzędny: " if higher else "")
                        + f"{', '.join(dep_names)} (zastępca kierownika {own.name})")
        name = _person_name(session, resp.manager_user_id) if resp else None
        if name:
            return (f"kierownik nadrzędny: {name} ({resp.name})" if higher
                    else f"{name} (kierownik {resp.name})")
        director = _unit_director_id(session, dept)
        dname = _person_name(session, director)
        if dname:
            unit = session.get(Unit, dept.unit_id) if dept else None
            return f"dyrektor jednostki: {dname}" + (f" ({unit.name})" if unit else "")
        return ("kierownik nadrzędny (nieprzypisany)" if higher
                else "kierownik komórki (nieprzypisany)")
    if ntype == "it_execute":
        name = _person_name(session, getattr(request, "assigned_to_user_id", None))
        return f"IT: {name}" if name else "Biuro Informatyki (IT)"
    return node.get("label") or ntype


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
    jako „od kogo" w skrzynce adresata, ale sama maila NIE dostaje (np.
    przełożony, który przejął i wysłał wniosek dwustopniowy, a teraz może
    wykonać też akceptację wyższą — krok zostaje, bez „czeka na Ciebie”).
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
            return
        s_name, s_email = _actor_sender(actor_user)
        from services.email_alerts import notify_workflow_stage
        for e in emails:
            defer(session, notify_workflow_stage, **{
                    "to_address": e,
                    "request_id": request.id,
                    "worker_name": request.worker_name,
                    "dept_name": dept.name if dept else "",
                    "stage_label": node.get("label") or node["type"],
                    "node_type": node["type"],
                    "from_name": s_name, "from_email": s_email,
                })
    except Exception as exc:
        _log.warning("Powiadomienie o etapie obiegu nie zostało wysłane: %s", exc)


def _notify_request_completed(session: Session, request: AccessRequest,
                              actor_user: Optional[User] = None) -> None:
    """Wniosek zrealizowany — powiadom KIEROWNIKA, który wybierał uprawnienia.

    To on wystąpił o konkretne uprawnienia i czeka na ich nadanie. Dopiero gdy
    kroku wyboru nie było (np. wniosek zamknięty wcześniej), wracamy do twórcy
    zgłoszenia (zwykle kadry). Nadawcą jest osoba z IT, która zrealizowała
    wniosek (`actor_user`).
    """
    try:
        target_id = request.created_by_id
        step = _selector_step(session, request)
        if step and step.actor_user_id:
            target_id = step.actor_user_id
        if not target_id or (actor_user is not None and target_id == actor_user.id):
            return   # brak adresata albo realizujący sam jest wnioskodawcą
        u = session.get(User, target_id)
        if not u or not u.email:
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
            pass
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
