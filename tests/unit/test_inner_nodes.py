"""Unit tests — inner workflow nodes."""

import json

from framework.schemas.agent_status import AgentStatus

from src.constants import APPI_DISCLOSURE_MARKER
from src.nodes.appi_disclosure_node import APPIDisclosureNode
from src.nodes.customer_context_load_node import CustomerContextLoadNode
from src.nodes.personalisation_engine_node import PersonalisationEngineNode
from src.nodes.recommendation_generate_node import RecommendationGenerateNode
from src.services.service import CatalogueService
from tests.conftest import CATALOGUE, RULES, FakeLLM, status_is


class TestCustomerContextLoad:
    def test_parses_serialized_payload(self):
        payload = json.dumps({"query": "夏物", "session_context": {"loyalty_tier": "gold", "browsed_categories": ["apparel"]}})
        out = CustomerContextLoadNode().execute({"user_input": payload, "session_id": "s1"})
        assert status_is(out["status"], AgentStatus.SUCCESS)
        assert out["validated_input"] == "夏物"
        assert out["session_context"]["loyalty_tier"] == "gold"
        assert out["session_context"]["browsed_categories"] == ["apparel"]

    def test_fallback_on_non_json(self):
        out = CustomerContextLoadNode().execute({"user_input": "plain text", "session_id": "s1"})
        assert out["session_context"]["loyalty_tier"] == "none"
        assert out["validated_input"] == "plain text"

    def test_malformed_session_fields_do_not_crash(self):
        # null / non-iterable values from a malformed payload must coerce safely, not raise.
        payload = json.dumps({"query": "q", "session_context": {"browsed_categories": None, "cart_items": 5, "loyalty_tier": None}})
        out = CustomerContextLoadNode().execute({"user_input": payload, "session_id": "s1"})
        assert out["session_context"]["browsed_categories"] == []
        assert out["session_context"]["cart_items"] == []
        assert out["session_context"]["loyalty_tier"] == "none"


class TestPersonalisationEngine:
    def test_computes_signals_from_catalogue_and_rules(self):
        svc = CatalogueService(catalogue=CATALOGUE, promotion_rules=RULES)
        state = {"session_context": {"browsed_categories": ["apparel"], "cart_items": [], "loyalty_tier": "gold"}}
        out = PersonalisationEngineNode(service=svc).execute(state)
        sig = out["personalisation_signals"]
        promo_ids = {p["id"] for p in sig["eligible_promotions"]}
        assert "PROMO-SUMMER" in promo_ids  # apparel match
        assert "PROMO-GOLD" in promo_ids    # gold tier match
        # cross_sell candidates are catalogue-derived (complement apparel)
        assert any(c["sku"] == "FOOT-010" for c in sig["cross_sell_candidates"])

    def test_no_signals_when_empty_catalogue(self):
        out = PersonalisationEngineNode(service=CatalogueService(catalogue=[], promotion_rules=[])).execute(
            {"session_context": {"browsed_categories": ["apparel"], "loyalty_tier": "gold"}}
        )
        sig = out["personalisation_signals"]
        assert sig["related_items"] == []
        assert sig["cross_sell_candidates"] == []


class TestRecommendationGenerate:
    def test_generates_copy_from_injected_llm(self):
        signals = {
            "loyalty_tier": "gold",
            "eligible_promotions": [{"id": "PROMO-SUMMER", "message": "夏物10%OFF"}],
            "related_items": [{"sku": "APRL-001", "name": "Linen Summer Shirt"}],
            "cross_sell_candidates": [{"sku": "FOOT-010", "name": "Canvas Sneakers"}],
        }
        node = RecommendationGenerateNode(llm=FakeLLM())
        out = node.execute({"validated_input": "夏物", "personalisation_signals": signals, "session_id": "s1"})
        assert status_is(out["status"], AgentStatus.SUCCESS)
        assert out["offer_copy"] == "夏物アパレルがおすすめです"
        assert out["promo_copy"] == "今だけ10%OFF"

    def test_cross_sell_is_deterministic_not_from_llm(self):
        # FakeLLM that hallucinates a priced cross-sell item must NOT leak into cross_sell.
        rogue = FakeLLM(content=json.dumps({"offer_copy": "x", "promo_copy": "y", "cross_sell": [{"sku": "FAKE-999", "price": 100}]}))
        signals = {"cross_sell_candidates": [{"sku": "FOOT-010", "name": "Canvas Sneakers"}]}
        out = RecommendationGenerateNode(llm=rogue).execute(
            {"validated_input": "q", "personalisation_signals": signals, "session_id": "s1"}
        )
        assert out["cross_sell"] == [{"sku": "FOOT-010", "name": "Canvas Sneakers"}]
        assert all("price" not in c for c in out["cross_sell"])


class TestAPPIDisclosure:
    def test_attaches_disclosure(self):
        out = APPIDisclosureNode().execute({"offer_copy": "夏物おすすめ", "promo_copy": "10%OFF", "session_id": "s1"})
        assert out["disclosure_attached"] is True
        assert APPI_DISCLOSURE_MARKER in out["offer_copy"]

    def test_idempotent(self):
        once = APPIDisclosureNode().execute({"offer_copy": "x", "session_id": "s1"})
        twice = APPIDisclosureNode().execute({"offer_copy": once["offer_copy"], "session_id": "s1"})
        assert twice["offer_copy"].count(APPI_DISCLOSURE_MARKER) == 1
