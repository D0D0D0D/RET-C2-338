"""AgentCore Platform v1.0 — LLM injection seam.

`recommendation_generate` depends on a `BaseLLM` (shared.services.llm.base_llm).
Tests inject a fake `BaseLLM` via graph config (`config["llm"]`), so unit and
integration tests never construct a real provider client or require provider
extras. Production (gateway constructs `Graph()` with no injected llm) lazily
builds the configured provider here.
"""

from __future__ import annotations

from typing import Any

from shared.services.llm.base_llm import BaseLLM

# Default provider for Agent 1000 templates is Claude (Anthropic).
DEFAULT_PROVIDER = "anthropic"


def build_llm(config: dict[str, Any] | None = None) -> BaseLLM:
    """Construct the configured LLM client.

    Called only when no llm was injected via config (production path). The
    provider client takes a ``config`` dict and requires ``config["api_key"]``,
    which must be sourced from the per-agent SecretProvider
    (``ctx.secrets.require('ANTHROPIC_API_KEY')``) — never from os.environ.
    The provider extra (e.g. langchain-anthropic) is provisioned by the
    runtime/gateway, not by unit tests (which inject a fake BaseLLM instead).
    """
    config = dict(config or {})
    config.setdefault("model", "claude-opus-4-8")
    provider = config.get("llm_provider", DEFAULT_PROVIDER)
    if provider == "anthropic":
        from shared.services.llm.anthropic_client import AnthropicClient

        return AnthropicClient(config=config)
    if provider == "openai":
        from shared.services.llm.openai_client import OpenAIClient

        return OpenAIClient(config=config)
    if provider == "bedrock":
        from shared.services.llm.bedrock_client import BedrockClient

        return BedrockClient(config=config)
    raise ValueError(f"Unknown llm_provider: {provider!r}")
