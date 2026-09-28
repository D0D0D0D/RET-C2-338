"""AgentCore Platform v1.0 — RET-C2-338 inner node: recommendation_generate."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services.llm_client import build_llm

_DEFAULT_SYSTEM_PROMPT = (
    "あなたは小売ブランドのマーケティング担当者です。提供されたパーソナライズ情報のみを根拠に、"
    "丁寧で魅力的な日本語のオファー文面と販促コピーを作成します。価格や在庫を断定せず、"
    "提供されていない商品やキャンペーンを作り出してはいけません。"
    "必ず JSON で {\"offer_copy\": str, \"promo_copy\": str} のみを返してください。"
)


class RecommendationGenerateNode(FunctionNode):
    """Generate offer copy + promo copy via the injected LLM.

    Cross-sell is NOT produced by the LLM: it is taken verbatim from the
    deterministic, catalogue+rules-derived shortlist (signals.cross_sell_candidates).
    This guarantees cross-sell never depends on an external pricing engine (F-3).
    """

    required_trust_level = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, llm: Any | None = None, system_prompt: str | None = None, config: dict | None = None) -> None:
        super().__init__()
        self._llm = llm
        self._system_prompt = system_prompt or _DEFAULT_SYSTEM_PROMPT
        self._config = config or {}

    def execute(self, state: AgentState) -> dict:
        signals = state.get("personalisation_signals", {}) or {}
        query = state.get("validated_input", state.get("user_input", ""))

        llm = self._llm or build_llm(self._config)
        messages = self._build_messages(query, signals)
        response = llm.complete(messages)
        content = response.get("content", "") if isinstance(response, dict) else str(response)

        offer_copy, promo_copy = self._parse(content)
        # Cross-sell is deterministic (catalogue + rules only) — never from the LLM.
        cross_sell = list(signals.get("cross_sell_candidates", []))

        # OBS-1: store only a msgpack-safe subset of the LLM response in State —
        # never the raw provider object (which may not be serializable).
        resp = response if isinstance(response, dict) else {}
        llm_response = {
            "content": content,
            "model": resp.get("model", ""),
            "usage": resp.get("usage", {}),
        }

        emit_trace_event(
            "recommendation_generated",
            {
                "anon_session": hashlib.sha256(str(state.get("session_id", "")).encode()).hexdigest()[:12],
                "recommendation_category": "personalised_offer",
                "n_promos": len(signals.get("eligible_promotions", [])),
                "n_cross_sell": len(cross_sell),
            },
            state,
        )
        return {
            "offer_copy": offer_copy,
            "promo_copy": promo_copy,
            "cross_sell": cross_sell,
            "llm_response": llm_response,
            "status": AgentStatus.SUCCESS.value,
        }

    def _build_messages(self, query: str, signals: dict) -> list[dict]:
        context = {
            "loyalty_tier": signals.get("loyalty_tier", "none"),
            "eligible_promotions": signals.get("eligible_promotions", []),
            "related_items": signals.get("related_items", []),
            "cross_sell_candidates": signals.get("cross_sell_candidates", []),
        }
        user_prompt = (
            f"顧客リクエスト: {query}\n"
            f"パーソナライズ情報(この情報のみ使用可): {json.dumps(context, ensure_ascii=False)}\n"
            "上記の eligible_promotions と related_items のみを根拠に、"
            "オファー文面(offer_copy)と販促コピー(promo_copy)を作成してください。"
        )
        return [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    @staticmethod
    def _parse(content: str) -> tuple[str, str]:
        try:
            data = json.loads(content)
            if isinstance(data, dict):
                return str(data.get("offer_copy", "")), str(data.get("promo_copy", ""))
        except (ValueError, TypeError):
            pass
        # Fallback: treat whole content as the offer copy.
        return content, ""
