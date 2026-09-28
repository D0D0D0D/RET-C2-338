"""AgentCore Platform v1.0 — RET-C2-338 State"""

# ADR-005: State must be a flat TypedDict — never Pydantic BaseModel.
# LangGraph checkpoints use msgpack serialization; Pydantic objects
# cause silent corruption.  Extend AgentState with agent-specific
# fields only.  Do NOT add credentials, secrets, or Pydantic models.

from __future__ import annotations

from framework.schemas.agent_state import AgentState


class State(AgentState):
    """RET-C2-338 agent state.

    Shared fields (user_input, status, session_id, node_history, error_log,
    formatted_output, response_metadata, hitl_*, etc.) are inherited from
    AgentState. Only domain fields are added below.

    Session-only constraint (APPI): `session_context` is request-scoped and is
    never persisted across sessions. No PII / credentials are stored here.
    """

    # Session-scoped customer context (browsed categories, cart items, loyalty
    # tier). Loaded by `customer_context_load`; cleared at session end.
    session_context: dict
    # Deterministic personalisation signals computed from session_context ×
    # product catalogue × promotion rules (eligible promos, related categories).
    personalisation_signals: dict
    # LLM-generated personalised offer message text.
    offer_copy: str
    # LLM-generated promotional copy.
    promo_copy: str
    # Cross-sell suggestions — derived from catalogue + promotion rules ONLY
    # (no external pricing engine dependency).
    cross_sell: list
    # True once the non-configurable APPI 2026 disclosure has been attached.
    disclosure_attached: bool
