"""AgentCore Platform v1.0 — RET-C2-338 inner node: personalisation_engine."""

from __future__ import annotations

from typing import Any

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services.service import CatalogueService


class PersonalisationEngineNode(FunctionNode):
    """Deterministically compute personalisation signals.

    signals = session_context × product_catalogue × promotion_rules.
    Pure matching logic (no LLM, no pricing engine): eligible promotions,
    related catalogue items, and loyalty-tier benefits. The cross-sell shortlist
    handed to generation is drawn from the catalogue + rules ONLY.
    """

    required_trust_level = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, service: CatalogueService | None = None) -> None:
        super().__init__()
        self._service = service or CatalogueService()

    def execute(self, state: AgentState) -> dict:
        session_context = state.get("session_context", {}) or {}
        browsed = {str(c).lower() for c in session_context.get("browsed_categories", [])}
        cart = {str(c).lower() for c in session_context.get("cart_items", [])}
        loyalty_tier = str(session_context.get("loyalty_tier", "none")).lower()

        catalogue = self._service.load_catalogue()
        rules = self._service.load_promotion_rules()

        related_items = self._related_items(catalogue, browsed, cart)
        eligible_promos = self._eligible_promotions(rules, browsed, cart, loyalty_tier)
        cross_sell_candidates = self._cross_sell(catalogue, related_items, cart)

        signals: dict[str, Any] = {
            "loyalty_tier": loyalty_tier,
            "related_items": related_items,
            "eligible_promotions": eligible_promos,
            "cross_sell_candidates": cross_sell_candidates,
        }
        emit_trace_event(
            "personalisation_computed",
            {
                "n_related": len(related_items),
                "n_promos": len(eligible_promos),
                "n_cross_sell": len(cross_sell_candidates),
            },
            state,
        )
        return {"personalisation_signals": signals, "status": AgentStatus.SUCCESS.value}

    @staticmethod
    def _related_items(catalogue: list[dict], browsed: set[str], cart: set[str]) -> list[dict]:
        wanted = browsed | cart
        out = []
        for item in catalogue:
            cat = str(item.get("category", "")).lower()
            if cat and cat in wanted:
                out.append({"sku": item.get("sku"), "name": item.get("name"), "category": item.get("category")})
        return out

    @staticmethod
    def _eligible_promotions(rules: list[dict], browsed: set[str], cart: set[str], loyalty_tier: str) -> list[dict]:
        signals = browsed | cart
        eligible = []
        for rule in rules:
            tiers = {str(t).lower() for t in rule.get("loyalty_tiers", [])}
            cats = {str(c).lower() for c in rule.get("categories", [])}
            tier_ok = not tiers or loyalty_tier in tiers
            cat_ok = not cats or bool(cats & signals)
            if tier_ok and cat_ok:
                eligible.append(
                    {"id": rule.get("id"), "message": rule.get("message"), "categories": rule.get("categories", [])}
                )
        return eligible

    @staticmethod
    def _cross_sell(catalogue: list[dict], related_items: list[dict], cart: set[str]) -> list[dict]:
        # Cross-sell = catalogue items complementary to browsed/related categories,
        # excluding what is already in the cart. Catalogue + rules only.
        related_cats = {str(i.get("category", "")).lower() for i in related_items}
        out = []
        for item in catalogue:
            sku = item.get("sku")
            name = str(item.get("name", "")).lower()
            complements = {str(c).lower() for c in item.get("complements", [])}
            if name in cart:
                continue
            if complements & related_cats:
                out.append({"sku": sku, "name": item.get("name"), "reason": "complements browsed categories"})
        return out
