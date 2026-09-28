"""Integration tests — full RetailPersonalisedOfferCopyAgent invoke (fake LLM)."""

from framework.schemas.agent_status import AgentStatus

from src.constants import APPI_DISCLOSURE_MARKER
from src.graph.graph import RetailPersonalisedOfferCopyAgent
from tests.conftest import status_is


def _build(agent_config):
    agent = RetailPersonalisedOfferCopyAgent(config=agent_config)
    agent.compile()
    return agent


class TestFullGraph:
    def test_happy_path_generates_offer_with_disclosure(self, agent_config, verified_ctx, session_input_context):
        agent = _build(agent_config)
        result = agent.invoke("夏物のおすすめは？", ctx=verified_ctx, input_context=session_input_context)

        assert status_is(result["status"], AgentStatus.SUCCESS)
        output = result["output"]
        assert isinstance(output, dict)
        # APPI disclosure present (S-3 gate passed) and flagged
        assert APPI_DISCLOSURE_MARKER in output["message"]
        assert output["disclosure_attached"] is True
        # personalised content from the fake LLM
        assert "夏物アパレルがおすすめです" in output["message"]
        # cross-sell present and catalogue-derived (no price field)
        assert output["cross_sell"]
        assert all("price" not in c for c in output["cross_sell"])

    def test_backbone_nodes_ran(self, agent_config, verified_ctx, session_input_context):
        agent = _build(agent_config)
        result = agent.invoke("おすすめ", ctx=verified_ctx, input_context=session_input_context)
        history = result.get("node_history", [])
        # Defensive: node_history entry format is framework-determined (str/dict/obj).
        for node in ("PreProcessNode", "PersonalisedOfferGraphNode", "PostProcessNode"):
            assert any(node in str(n) for n in history), f"{node} missing from node_history: {history}"
