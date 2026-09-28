"""AgentCore Platform v1.0 — RET-C2-338 outer graph (Cat 2).

Cat 2: outer AgentBaseGraph backbone with the `main` slot filled by a GraphNode
(`PersonalisedOfferGraphNode`) wrapping the inner DomainWorkflowGraph. Domain
complexity is encapsulated inside the subgraph; the backbone is the fixed
5-node pipeline. add_edges()/route() are NOT overridden.

Backbone: START → initialize → pre_process → main → {route} → post_process → finalize → END
"""

from __future__ import annotations

import json
from typing import ClassVar

from framework.graph.agent_base_graph import AgentBaseGraph
from framework.nodes.graph_node import GraphNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel

from src.nodes.post_process_node import PostProcessNode
from src.nodes.pre_process_node import PreProcessNode
from src.schemas.state import State

# Config keys forwarded from the outer graph into the inner workflow.
_INNER_CONFIG_KEYS = (
    "llm",
    "llm_provider",
    "model",
    "system_prompt",
    "catalogue",
    "promotion_rules",
    "product_catalogue_path",
    "promotion_rules_path",
)


class PersonalisedOfferGraphNode(GraphNode):
    """`main` slot: wraps the inner personalised-offer workflow graph.

    The framework does not propagate the outer input_context into a subgraph, so
    extract_input() serializes {query, session_context} into the inner user_input.
    """

    error_strategy: ClassVar[str] = "propagate"
    propagate_hitl: ClassVar[bool] = False
    required_trust_level = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, inner_config: dict | None = None) -> None:
        super().__init__()
        self._inner_config = inner_config or {}

    def execute(self, state: AgentState) -> dict:
        # pre_process → main is an unconditional backbone edge: if an upstream
        # node (e.g. pre_process S-2 reject) already set status=error, pass it
        # through unchanged instead of running the subgraph (route() then sends
        # the flow to finalize).
        status = state.get("status")
        if status == AgentStatus.ERROR or status == AgentStatus.ERROR.value:
            return {}
        return super().execute(state)

    def get_subgraph(self):
        from src.graph.domain_workflow_graph import DomainWorkflowGraph

        return DomainWorkflowGraph(config=self._inner_config)

    def extract_input(self, state: AgentState) -> str:
        payload = {
            "query": state.get("validated_input", state.get("user_input", "")),
            "session_context": state.get("input_context", {}) or {},
        }
        # default=str so a non-JSON-serialisable value in input_context downgrades
        # to a safe string instead of crashing the node (malformed input safety).
        return json.dumps(payload, ensure_ascii=False, default=str)

    def merge_output(self, state: AgentState, sub_result: dict) -> dict:
        return {
            "offer_copy": sub_result.get("offer_copy", ""),
            "promo_copy": sub_result.get("promo_copy", ""),
            "cross_sell": sub_result.get("cross_sell", []),
            "disclosure_attached": sub_result.get("disclosure_attached", False),
            "status": sub_result.get("status"),
        }


class RetailPersonalisedOfferCopyAgent(AgentBaseGraph):
    """RET-C2-338 — Retail Personalised Offer & Promo Copy Generator."""

    @property
    def name(self) -> str:
        return "ret_c2_338"

    @property
    def state_schema(self) -> type:
        return State

    def register_nodes(self) -> None:
        super().register_nodes()  # injects initialize + finalize
        inner_config = {k: self.config[k] for k in _INNER_CONFIG_KEYS if k in self.config}
        self._nodes["pre_process"] = PreProcessNode()
        self._nodes["main"] = PersonalisedOfferGraphNode(inner_config=inner_config)
        self._nodes["post_process"] = PostProcessNode()

    # add_edges() / route() are NOT overridden — backbone wiring is the framework's.


# Alias expected by config/agent.yaml `class:` and server.py.
Graph = RetailPersonalisedOfferCopyAgent
