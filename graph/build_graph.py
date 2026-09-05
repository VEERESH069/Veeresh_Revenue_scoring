"""Assemble the recovery workflow with optional LangGraph support."""

from graph.nodes import check_policy_gate, classify_root_cause, execute_action, generate_nudge, ingest_event, judge_nudge_quality, log_audit, update_memory, validate_output


def route_after_judge(state: dict) -> str:
    """Skip provider execution for terminal decisions and preserve their audit path."""
    return "execute" if state.get("policy_decision") in {"retry", "nudge", "switch_method", "await_promise"} else "memory"


def build_graph():
    """Build a stateful graph; the fallback keeps local demos usable without extras."""
    try:
        from langgraph.graph import END, StateGraph
        graph = StateGraph(dict)
        for name, node in [("ingest", ingest_event), ("classify", classify_root_cause), ("policy", check_policy_gate), ("nudge", generate_nudge), ("validate", validate_output), ("judge", judge_nudge_quality), ("execute", execute_action), ("memory", update_memory), ("audit", log_audit)]:
            graph.add_node(name, node)
        graph.set_entry_point("ingest")
        graph.add_edge("ingest", "classify")
        graph.add_edge("classify", "policy")
        graph.add_edge("policy", "nudge")
        graph.add_edge("nudge", "validate")
        graph.add_edge("validate", "judge")
        graph.add_conditional_edges("judge", route_after_judge, {"execute": "execute", "memory": "memory"})
        graph.add_edge("execute", "memory")
        graph.add_edge("memory", "audit")
        graph.add_edge("audit", END)
        return graph.compile()
    except Exception:
        def local_runner(state):
            for node in (ingest_event, classify_root_cause, check_policy_gate, generate_nudge, validate_output, judge_nudge_quality):
                state = node(state)
            if route_after_judge(state) == "execute":
                state = execute_action(state)
            else:
                state = {**state, "action_result": {"success": True, "status": "no_auto_action"}, "outcome": "closed" if state.get("policy_decision") == "close" else "escalated"}
            state = update_memory(state)
            state = log_audit(state)
            return state
        return local_runner
