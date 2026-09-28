"""Shared test fixtures for RET-C2-338."""

from __future__ import annotations

import json

import pytest

from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel

CATALOGUE = [
    {"sku": "APRL-001", "name": "Linen Summer Shirt", "category": "apparel", "complements": ["accessories"]},
    {"sku": "FOOT-010", "name": "Canvas Sneakers", "category": "footwear", "complements": ["apparel"]},
    {"sku": "ACCS-020", "name": "Woven Leather Belt", "category": "accessories", "complements": ["apparel"]},
]

RULES = [
    {"id": "PROMO-SUMMER", "message": "夏物アパレル10%OFF", "categories": ["apparel"], "loyalty_tiers": []},
    {"id": "PROMO-GOLD", "message": "ゴールド会員ポイント2倍", "categories": [], "loyalty_tiers": ["gold"]},
]


class FakeLLM:
    """Duck-typed BaseLLM for hermetic tests (no provider extra required)."""

    def __init__(self, content: str | None = None):
        self.content = content if content is not None else json.dumps(
            {"offer_copy": "夏物アパレルがおすすめです", "promo_copy": "今だけ10%OFF"},
            ensure_ascii=False,
        )
        self.calls: list = []

    def complete(self, messages: list) -> dict:
        self.calls.append(messages)
        return {
            "content": self.content,
            "tool_calls": [],
            "model": "fake-model",
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "model": "fake-model"},
        }

    def stream(self, messages: list):
        yield self.content

    def bind_tools(self, tools: list):
        return self


def status_is(value, status: AgentStatus) -> bool:
    """Robust status comparison (enum member or its string value)."""
    return value == status or value == status.value


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def agent_config(fake_llm: FakeLLM) -> dict:
    return {"llm": fake_llm, "catalogue": CATALOGUE, "promotion_rules": RULES}


@pytest.fixture
def verified_ctx() -> InvocationContext:
    return InvocationContext(session_id="sess-1", caller_trust_level=TrustLevel.VERIFIED_EXTERNAL)


@pytest.fixture
def session_input_context() -> dict:
    return {
        "channel": "web",
        "browsed_categories": ["apparel"],
        "cart_items": ["Canvas Sneakers"],
        "loyalty_tier": "gold",
    }


@pytest.fixture
def case_payload() -> str:
    """`tests/integration/test_graph.py::test_happy_path_generates_offer_with_disclosure` と同じ入力。"""
    return "夏物のおすすめは？"


@pytest.fixture
def live_input_context(session_input_context: dict) -> dict:
    """live smoke も integration と同じ session-only personalization context を使う。"""
    return dict(session_input_context)
