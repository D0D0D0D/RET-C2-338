"""Unit tests — PreProcessNode (InputParse + S-2 session-only gate)."""

import inspect

from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel

from src.nodes.pre_process_node import PreProcessNode
from tests.conftest import status_is


class TestPreProcessNode:
    def setup_method(self):
        self.node = PreProcessNode()

    def test_valid_input(self):
        result = self.node.execute({"user_input": "  夏物のおすすめ  ", "input_context": {"channel": "app"}})
        assert status_is(result["status"], AgentStatus.SUCCESS)
        assert result["validated_input"] == "夏物のおすすめ"
        assert result["enriched_context"]["channel"] == "app"

    def test_empty_input(self):
        result = self.node.execute({"user_input": "   ", "input_context": {}})
        assert status_is(result["status"], AgentStatus.ERROR)

    def test_required_trust_level_is_verified_external(self):
        assert PreProcessNode.required_trust_level == TrustLevel.VERIFIED_EXTERNAL

    def test_s2_session_only_rejects_persistent_identifier(self):
        state = {"user_input": "x", "input_context": {"persistent_profile_id": "P-9"}, "error_log": []}
        out = self.node._extra_security_gate_input(state)
        assert status_is(out["status"], AgentStatus.ERROR)
        assert any("session-only" in e for e in out["error_log"])

    def test_s2_passes_for_clean_context(self):
        state = {"user_input": "x", "input_context": {"channel": "web"}, "status": "pending", "error_log": []}
        out = self.node._extra_security_gate_input(state)
        assert not status_is(out.get("status"), AgentStatus.ERROR)

    def test_execute_signature(self):
        params = list(inspect.signature(PreProcessNode.execute).parameters.keys())
        assert params[1] == "state"
        assert "_invoke_impl" not in PreProcessNode.__dict__
