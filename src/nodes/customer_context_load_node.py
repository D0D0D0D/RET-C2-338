"""AgentCore Platform v1.0 — RET-C2-338 inner node: customer_context_load."""

from __future__ import annotations

import hashlib
import json

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event


def _anon_session(state: AgentState) -> str:
    """Anonymised session id for audit (no raw session id leaks into logs)."""
    sid = str(state.get("session_id", ""))
    return hashlib.sha256(sid.encode("utf-8")).hexdigest()[:12] if sid else "anonymous"


def _as_list(value: object) -> list:
    """Coerce caller-provided values to a list defensively (malformed input safety)."""
    return list(value) if isinstance(value, (list, tuple)) else []


class CustomerContextLoadNode(FunctionNode):
    """Load session-scoped customer context from the serialized inner input.

    The outer GraphNode serializes ``{"query": ..., "session_context": ...}`` into
    the inner graph's user_input (the framework does not propagate the outer
    input_context into a subgraph). This node restores session_context. It is
    request-scoped only — nothing is persisted across sessions (APPI session-only).
    """

    required_trust_level = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: AgentState) -> dict:
        raw = state.get("user_input", "")
        try:
            payload = json.loads(raw) if raw else {}
        except (ValueError, TypeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}

        query = payload.get("query", raw if isinstance(raw, str) else "")
        if not isinstance(query, str):
            query = str(query)
        sc = payload.get("session_context", {})
        if not isinstance(sc, dict):
            sc = {}

        session_context = {
            "browsed_categories": _as_list(sc.get("browsed_categories")),
            "cart_items": _as_list(sc.get("cart_items")),
            "loyalty_tier": str(sc.get("loyalty_tier") or "none"),
        }

        emit_trace_event(
            "customer_context_loaded",
            {
                "anon_session": _anon_session(state),
                "loyalty_tier": session_context["loyalty_tier"],
                "n_browsed": len(session_context["browsed_categories"]),
                "n_cart": len(session_context["cart_items"]),
            },
            state,
        )
        return {
            "validated_input": query,
            "session_context": session_context,
            "status": AgentStatus.SUCCESS.value,
        }
