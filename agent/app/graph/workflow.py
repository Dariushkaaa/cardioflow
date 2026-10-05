from langgraph.graph import END, START, StateGraph

from app.graph.nodes import (
    backend_report_node,
    chat_node,
    clarify_symptoms_node,
    confirmation_node,
    greeting_node,
    has_report_data,
    nlu_node,
    rag_advice_node,
    slots_proposal_node,
)
from app.graph.state import AgentState


def route_event(state):
    return "greeting" if state.get("event_type") == "init_onboarding" else "nlu"


def route_intent(state):
    parsed = state.get("parsed_report") or {}
    if parsed.get("intent") == "ask_advice" and not has_report_data(parsed):
        return "rag"
    if has_report_data(parsed):
        return "report"
    if parsed.get("intent") == "complain_side_effects":
        return "clarify"
    return "chat"


def route_after_report(state):
    if state.get("error"):
        return "end"
    if state.get("action_required") in ("book_appointment", "repeat_measurement"):
        return "clarify"
    if state.get("risk_level") in ("critical", "warning"):
        return "clarify"
    return "confirm"


def route_after_clarify(state):
    return "slots" if state.get("action_required") == "book_appointment" else "end"


def build_workflow():
    g = StateGraph(AgentState)
    g.add_node("greeting", greeting_node)
    g.add_node("nlu", nlu_node)
    g.add_node("rag", rag_advice_node)
    g.add_node("chat", chat_node)
    g.add_node("report", backend_report_node)
    g.add_node("clarify", clarify_symptoms_node)
    g.add_node("slots", slots_proposal_node)
    g.add_node("confirm", confirmation_node)

    g.add_conditional_edges(START, route_event, {"greeting": "greeting", "nlu": "nlu"})
    g.add_edge("greeting", END)
    g.add_conditional_edges(
        "nlu", route_intent, {"rag": "rag", "report": "report", "clarify": "clarify", "chat": "chat"}
    )
    g.add_edge("rag", END)
    g.add_edge("chat", END)
    g.add_conditional_edges("report", route_after_report, {"clarify": "clarify", "confirm": "confirm", "end": END})
    g.add_conditional_edges("clarify", route_after_clarify, {"slots": "slots", "end": END})
    g.add_edge("slots", END)
    g.add_edge("confirm", END)
    return g.compile()


workflow = build_workflow()
