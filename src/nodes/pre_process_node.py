"""AgentCore Platform v1.0 — RET-C2-338 PreProcessNode (InputParse)."""

# Node contract:
#  - Extend FunctionNode; implement execute(state) -> dict; return only changed keys
#  - Return AgentStatus enum constants — never plain strings
#  - S-1 enforced by BaseNode.__call__ via required_trust_level
#  - S-2 domain extension via _extra_security_gate_input() (default PII mask runs first)

from __future__ import annotations

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

# Persistent / cross-session identifier keys that violate the APPI session-only
# constraint. Their presence in input_context means the caller is trying to feed
# a persistent customer profile — rejected at the S-2 gate.
_FORBIDDEN_PERSISTENT_KEYS = frozenset(
    {"persistent_profile_id", "cross_session_id", "customer_master_id", "persistent_user_id"}
)


class PreProcessNode(FunctionNode):
    """Validate and enrich the incoming personalisation request.

    S-1: customer-facing minimum trust = VERIFIED_EXTERNAL.
    """

    required_trust_level = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: AgentState) -> dict:
        user_input = state.get("user_input", "")
        input_context = state.get("input_context", {})  # read-only

        if not user_input or not user_input.strip():
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["PreProcessNode: user_input is empty or missing"],
            }

        emit_trace_event("input_parsed", {"channel": input_context.get("channel", "unknown")}, state)
        return {
            "validated_input": user_input.strip(),
            "enriched_context": {
                "source": "ret_c2_338",
                "channel": input_context.get("channel", "unknown"),
                "locale": input_context.get("locale", "ja-JP"),
            },
            "status": AgentStatus.SUCCESS.value,
        }

    def _extra_security_gate_input(self, state: AgentState) -> AgentState:
        """S-2 domain extension: enforce APPI session-only constraint.

        The default FunctionNode PII scan has already masked PII in scan fields.
        Here we reject requests that carry a persistent / cross-session profile
        identifier (which would breach the session-only personalisation promise).
        """
        input_context = state.get("input_context", {}) or {}
        offending = sorted(_FORBIDDEN_PERSISTENT_KEYS & set(input_context.keys()))
        if offending:
            state["status"] = AgentStatus.ERROR.value
            state["error_log"] = list(state.get("error_log", [])) + [
                f"PreProcessNode: S-2 session-only violation — persistent identifier(s) {offending} "
                "not allowed (APPI session-only personalisation)"
            ]
        return state
