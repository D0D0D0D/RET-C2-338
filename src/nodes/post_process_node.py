"""AgentCore Platform v1.0 — RET-C2-338 PostProcessNode (ResponseFormat + S-3)."""

from __future__ import annotations

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.constants import APPI_DISCLOSURE_MARKER


class PostProcessNode(FunctionNode):
    """Assemble the customer-facing message and enforce the APPI disclosure gate.

    S-3 (CRITICAL): `_extra_security_gate_output()` verifies the non-configurable
    APPI 2026 disclosure marker is present in the formatted output. If absent, it
    raises — fail-closed — so non-compliant output never reaches the customer.
    This is independent of the `appi_disclosure` node (defense in depth).
    """

    required_trust_level = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: AgentState) -> dict:
        offer_copy = state.get("offer_copy", "")
        promo_copy = state.get("promo_copy", "")
        cross_sell = state.get("cross_sell", []) or []

        sections = [offer_copy]
        if promo_copy:
            sections.append(promo_copy)
        if cross_sell:
            names = "、".join(str(c.get("name", c.get("sku", ""))) for c in cross_sell)
            sections.append(f"あわせておすすめ: {names}")

        formatted_output = {
            "message": "\n\n".join(s for s in sections if s),
            "offer_copy": offer_copy,
            "promo_copy": promo_copy,
            "cross_sell": cross_sell,
            "disclosure_attached": bool(state.get("disclosure_attached", False)),
        }

        emit_trace_event("response_formatted", {"n_cross_sell": len(cross_sell)}, state)
        return {
            "formatted_output": formatted_output,
            "result": formatted_output["message"],
            "status": AgentStatus.SUCCESS.value,
        }

    def _extra_security_gate_output(self, result: dict) -> dict:
        """S-3 / S-5: fail-closed APPI 2026 disclosure presence verification."""
        formatted = result.get("formatted_output", {})
        message = formatted.get("message", "") if isinstance(formatted, dict) else ""
        if APPI_DISCLOSURE_MARKER not in message:
            raise RuntimeError(
                "S-3 APPI gate: mandatory APPI 2026 disclosure marker missing from output. "
                "Output blocked (non-configurable compliance gate)."
            )
        return result
