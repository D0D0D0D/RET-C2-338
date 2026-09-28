"""AgentCore Platform v1.0 — RET-C2-338 inner domain workflow graph."""

from __future__ import annotations

from langgraph.graph import END, START

from framework.graph.base_graph import BaseGraph
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus

from src.nodes.appi_disclosure_node import APPIDisclosureNode
from src.nodes.customer_context_load_node import CustomerContextLoadNode
from src.nodes.personalisation_engine_node import PersonalisationEngineNode
from src.nodes.recommendation_generate_node import RecommendationGenerateNode
from src.schemas.state import State
from src.services.service import CatalogueService


class DomainWorkflowGraph(BaseGraph):
    """Inner Cat 2 workflow: context load → personalise → generate → APPI disclosure.

    Inherits BaseGraph (fully custom topology). Instantiated by
    PersonalisedOfferGraphNode.get_subgraph() in graph.py. The outer GraphNode
    serializes {query, session_context} into user_input; this graph restores the
    session context, computes personalisation signals, generates the copy, and
    attaches the mandatory APPI disclosure.
    """

    @property
    def name(self) -> str:
        return "personalised_offer_workflow"

    @property
    def state_schema(self) -> type:
        return State

    def _validate_config(self) -> None:
        # No mandatory config: catalogue/rules/llm are optional injections
        # (production sources them via gateway config / secrets).
        pass

    def _build_service(self) -> CatalogueService:
        return CatalogueService(
            catalogue=self.config.get("catalogue"),
            promotion_rules=self.config.get("promotion_rules"),
            catalogue_path=self.config.get("product_catalogue_path"),
            promotion_rules_path=self.config.get("promotion_rules_path"),
        )

    def register_nodes(self) -> None:
        # No super() — BaseGraph.register_nodes is abstract. Do NOT register
        # initialize/finalize (outer backbone concern).
        self._nodes["customer_context_load"] = CustomerContextLoadNode()
        self._nodes["personalisation_engine"] = PersonalisationEngineNode(service=self._build_service())
        self._nodes["recommendation_generate"] = RecommendationGenerateNode(
            llm=self.config.get("llm"),
            system_prompt=self.config.get("system_prompt"),
            config=self.config,
        )
        self._nodes["appi_disclosure"] = APPIDisclosureNode()

    def add_edges(self) -> None:
        self._sg.add_edge(START, "customer_context_load")
        self._sg.add_edge("customer_context_load", "personalisation_engine")
        self._sg.add_edge("personalisation_engine", "recommendation_generate")
        self._sg.add_edge("recommendation_generate", "appi_disclosure")
        self._sg.add_edge("appi_disclosure", END)

    def route(self, state: AgentState) -> str:
        # Linear topology — route is required by the ABC but never reached unless
        # add_conditional_edges() references it.
        return END if state.get("status") == AgentStatus.ERROR.value else "appi_disclosure"

    def get_output(self, state: AgentState) -> dict:
        """Shape sub_result for PersonalisedOfferGraphNode.merge_output()."""
        return {
            "offer_copy": state.get("offer_copy", ""),
            "promo_copy": state.get("promo_copy", ""),
            "cross_sell": state.get("cross_sell", []),
            "disclosure_attached": state.get("disclosure_attached", False),
            "status": state.get("status"),
            "trace_id": state.get("trace_id"),
            "correlation_id": state.get("correlation_id"),
            "node_history": state.get("node_history", []),
        }
