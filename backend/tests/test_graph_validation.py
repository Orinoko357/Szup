"""Jednostkowe: walidacja grafu obiegu (C1) — parse_graph odrzuca złe grafy."""
from __future__ import annotations

import json

import pytest

from services.workflow import parse_graph, WorkflowGraphError


def _g(nodes, edges):
    return json.dumps({"nodes": nodes, "edges": edges})


def test_valid_linear_graph_ok():
    g = _g(
        [{"id": "n1", "type": "start", "label": "S"},
         {"id": "n2", "type": "it_execute", "label": "IT"},
         {"id": "n3", "type": "end", "label": "E"}],
        [{"from": "n1", "to": "n2"}, {"from": "n2", "to": "n3"}],
    )
    parsed = parse_graph(g)          # nie rzuca
    assert parsed["nodes"] and parsed["edges"]


def test_node_without_outgoing_edge_rejected():
    # n2 nie ma wyjścia → cichy auto-complete (C1). Musi być odrzucone.
    g = _g(
        [{"id": "n1", "type": "start"},
         {"id": "n2", "type": "it_execute"},
         {"id": "n3", "type": "end"}],
        [{"from": "n1", "to": "n2"}],   # brak n2->n3
    )
    with pytest.raises(WorkflowGraphError):
        parse_graph(g)


def test_unreachable_end_rejected():
    g = _g(
        [{"id": "n1", "type": "start"},
         {"id": "n2", "type": "it_execute"},
         {"id": "n3", "type": "end"}],
        [{"from": "n1", "to": "n2"}, {"from": "n2", "to": "n2"}],  # pętla, end nieosiągalny
    )
    with pytest.raises(WorkflowGraphError):
        parse_graph(g)


def test_multiple_outgoing_edges_rejected():
    g = _g(
        [{"id": "n1", "type": "start"},
         {"id": "n2", "type": "it_execute"},
         {"id": "n3", "type": "end"},
         {"id": "n4", "type": "end"}],
        [{"from": "n1", "to": "n2"}, {"from": "n2", "to": "n3"}, {"from": "n2", "to": "n4"}],
    )
    with pytest.raises(WorkflowGraphError):
        parse_graph(g)


def test_end_with_outgoing_edge_rejected():
    g = _g(
        [{"id": "n1", "type": "start"},
         {"id": "n2", "type": "end"}],
        [{"from": "n1", "to": "n2"}, {"from": "n2", "to": "n1"}],
    )
    with pytest.raises(WorkflowGraphError):
        parse_graph(g)


def test_edge_to_unknown_node_rejected():
    g = _g(
        [{"id": "n1", "type": "start"},
         {"id": "n2", "type": "end"}],
        [{"from": "n1", "to": "n2"}, {"from": "n2", "to": "ghost"}],
    )
    with pytest.raises(WorkflowGraphError):
        parse_graph(g)
