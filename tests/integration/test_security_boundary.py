"""Proof-of-Boundary — S-1 trust, S-2 session-only, S-3 APPI fail-closed."""

from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel

from src.graph.graph import RetailPersonalisedOfferCopyAgent
from src.nodes.post_process_node import PostProcessNode
from src.nodes.pre_process_node import PreProcessNode
from tests.conftest import status_is


def _build(agent_config):
    agent = RetailPersonalisedOfferCopyAgent(config=agent_config)
    agent.compile()
    return agent


class TestS1TrustGate:
    def test_anonymous_caller_denied_at_node(self):
        # PreProcessNode requires VERIFIED_EXTERNAL; ANONYMOUS caller is denied by __call__.
        node = PreProcessNode()
        result = node({"user_input": "x", "caller_trust_level": TrustLevel.ANONYMOUS.value,
                       "node_history": [], "error_log": [], "execution_time": {}})
        assert status_is(result["status"], AgentStatus.ERROR)
        assert any("S-1 trust gate denied" in e for e in result["error_log"])

    def test_anonymous_caller_errors_full_graph(self, agent_config, session_input_context):
        agent = _build(agent_config)
        ctx = InvocationContext(session_id="s1", caller_trust_level=TrustLevel.ANONYMOUS)
        result = agent.invoke("おすすめ", ctx=ctx, input_context=session_input_context)
        assert status_is(result["status"], AgentStatus.ERROR)


class TestS2SessionOnlyGate:
    def test_persistent_identifier_rejected_full_graph(self, agent_config, verified_ctx):
        agent = _build(agent_config)
        bad_context = {"channel": "web", "persistent_profile_id": "P-9", "loyalty_tier": "gold"}
        result = agent.invoke("おすすめ", ctx=verified_ctx, input_context=bad_context)
        assert status_is(result["status"], AgentStatus.ERROR)


class TestS3APPIGate:
    def test_missing_disclosure_blocks_output(self):
        # PostProcessNode S-3 gate raises when the APPI marker is absent; __call__
        # catches the raise and returns status=error (fail-closed).
        node = PostProcessNode()
        result = node({
            "offer_copy": "開示なしオファー", "promo_copy": "", "cross_sell": [],
            "disclosure_attached": False, "caller_trust_level": TrustLevel.VERIFIED_EXTERNAL.value,
            "node_history": [], "error_log": [], "execution_time": {},
        })
        assert status_is(result["status"], AgentStatus.ERROR)
        assert any("APPI" in e for e in result["error_log"])
