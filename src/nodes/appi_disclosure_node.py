"""AgentCore Platform v1.0 — RET-C2-338 inner node: appi_disclosure."""

from __future__ import annotations

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.constants import APPI_DISCLOSURE_MARKER, APPI_DISCLOSURE_TEXT


class APPIDisclosureNode(FunctionNode):
    """Attach the non-configurable APPI 2026 AI-recommendation disclosure.

    The disclosure text is hard-coded (compliance-by-construction): citizens may
    configure brand voice but can never disable or alter this disclosure. Its
    presence is independently verified fail-closed by PostProcessNode's S-3 gate.
    """

    required_trust_level = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: AgentState) -> dict:
        offer_copy = state.get("offer_copy", "")
        promo_copy = state.get("promo_copy", "")

        # Idempotent: don't double-append if the marker is already present.
        if APPI_DISCLOSURE_MARKER not in offer_copy:
            offer_copy = f"{offer_copy}\n\n{APPI_DISCLOSURE_TEXT}".strip()

        emit_trace_event("appi_disclosure_attached", {"marker": APPI_DISCLOSURE_MARKER}, state)
        return {
            "offer_copy": offer_copy,
            "promo_copy": promo_copy,
            "disclosure_attached": True,
            "status": AgentStatus.SUCCESS.value,
        }
