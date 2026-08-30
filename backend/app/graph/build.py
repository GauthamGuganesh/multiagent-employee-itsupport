"""Graph assembly.

Topology (edges select, nodes mutate; Command-returning nodes route themselves):

    START → ingest → supervisor ⇄ {identity, endpoint, network, security}
    supervisor → ask_prepare → ask_wait(interrupt) → supervisor
    supervisor → confirmation_prepare → confirmation_wait(interrupt)
                 → execute_action → resolution | escalation
    confirmation_prepare → approval | escalation
    supervisor → ticket_status → close_direct | escalation
    resolution | close_direct | approval | escalation → END
"""
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.graph.specialists.runner import make_specialist_node
from app.graph.specialists.specs import SPECS
from app.graph.state import SupportState
from app.graph.supervisor import supervisor_node
from app.graph.workflows.approval import approval_node
from app.graph.workflows.common import ingest_node
from app.graph.workflows.confirmation import (
    confirmation_prepare,
    confirmation_wait,
    execute_action,
)
from app.graph.workflows.escalation import escalation_node
from app.graph.workflows.need_info import ask_prepare, ask_wait
from app.graph.workflows.resolution import close_direct_node, resolution_node
from app.graph.workflows.ticket_status import ticket_status_node

SPECIALIST_NODES = tuple(SPECS.keys())


def build_graph(checkpointer=None):
    g = StateGraph(SupportState)

    g.add_node("ingest", ingest_node)
    g.add_node(
        "supervisor",
        supervisor_node,
        destinations=(
            *SPECIALIST_NODES, "ask_prepare", "confirmation_prepare", "approval",
            "escalation", "resolution", "ticket_status", "close_direct",
        ),
    )
    for spec in SPECS.values():
        g.add_node(spec.name, make_specialist_node(spec))

    g.add_node("ask_prepare", ask_prepare)
    g.add_node("ask_wait", ask_wait)
    g.add_node(
        "confirmation_prepare",
        confirmation_prepare,
        destinations=("confirmation_wait", "approval", "escalation", "supervisor"),
    )
    g.add_node(
        "confirmation_wait",
        confirmation_wait,
        destinations=("execute_action", "supervisor"),
    )
    g.add_node("execute_action", execute_action, destinations=("resolution", "escalation"))
    g.add_node("ticket_status", ticket_status_node, destinations=("close_direct", "escalation"))
    g.add_node("resolution", resolution_node)
    g.add_node("close_direct", close_direct_node)
    g.add_node("approval", approval_node, destinations=(END, "escalation"))
    g.add_node("escalation", escalation_node)

    g.add_edge(START, "ingest")
    g.add_edge("ingest", "supervisor")
    for name in SPECIALIST_NODES:
        g.add_edge(name, "supervisor")
    g.add_edge("ask_prepare", "ask_wait")
    g.add_edge("ask_wait", "supervisor")
    g.add_edge("resolution", END)
    g.add_edge("close_direct", END)
    g.add_edge("escalation", END)

    return g.compile(checkpointer=checkpointer or InMemorySaver())
