"""AGENTIC STAR Marketplace container entry adapter for RET-C2-338."""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

from framework.schemas.invocation_context import InvocationContext
from framework.secrets.base import SecretProvider
from framework.secrets.context import current_secrets

try:
    from framework.utils.config_loader import load_agent_config
except ImportError:  # AgentCore 1.0.0 / 1.0.1 compatibility
    from framework.utils.config_loader import load_config

    def load_agent_config(agent_dir: Path) -> dict[str, Any]:
        config_path = agent_dir / "config" / "config.yaml"
        return load_config(str(config_path)) if config_path.exists() else {}


try:
    from shared.secrets.env_provider import EnvProvider
except ImportError:  # AgentCore 1.0.0 / 1.0.1 compatibility

    class EnvProvider(SecretProvider):
        """AgentCore 1.0.2-compatible process environment provider."""

        def __init__(self, *, namespace: str = "", agent_name: str = "") -> None:
            self._namespace = namespace
            self._agent_name = agent_name

        def get(self, key: str, default: str | None = None) -> str | None:
            return os.environ.get(key, default)


from shared.services.llm.base_llm import BaseLLM

from src.graph.graph import RetailPersonalisedOfferCopyAgent

_NAMESPACE = "ret"
_AGENT_NAME = "RET-C2-338"
_PROVIDER_AGENT_NAME = "ret_c2_338"

_AZURE_OPENAI_SECRET_KEYS = (
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_DEPLOYMENT",
)
_REQUIRED_SECRET_KEYS = _AZURE_OPENAI_SECRET_KEYS
_ALLOWED_SECRET_KEYS = frozenset(_REQUIRED_SECRET_KEYS)


class _AllowlistedEnvironmentProvider(EnvProvider):  # type: ignore[misc]
    """Expose only this single-agent container's Azure connection values."""

    def __init__(self) -> None:
        super().__init__(namespace=_NAMESPACE, agent_name=_PROVIDER_AGENT_NAME)

    def get(self, key: str, default: str | None = None) -> str | None:
        if key not in _ALLOWED_SECRET_KEYS:
            return default
        value = super().get(key)
        return value if value else default


def _require_clean_secret(provider: SecretProvider, key: str) -> str:
    """Require one unmodified, non-blank, single-line Azure value."""

    value = provider.require(key)
    if value != value.strip() or not value.strip() or "\n" in value or "\r" in value:
        raise ValueError(f"Marketplace secret {key!r} must be a clean non-empty single-line value")
    return value


def _require_azure_endpoint(provider: SecretProvider) -> str:
    """Reject ``AZURE_OPENAI_ENDPOINT`` values that are not a bare Azure resource endpoint.

    ``AzureOpenAIClient`` appends its own ``/openai/v1/`` path, so anything
    beyond a scheme and host silently produces a broken request URL, and the
    failure surfaces inside ``complete()``. A node that swallows that exception
    degrades quietly while the invocation still reports ``status: success``,
    which is why this has to be a startup check. The value is reported here,
    never repaired.
    """

    endpoint = _require_clean_secret(provider, "AZURE_OPENAI_ENDPOINT")
    parts = urlsplit(endpoint)
    try:
        port = parts.port
    except ValueError:
        port = -1
    if (
        parts.scheme not in ("http", "https")
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or port == -1
        or parts.path.strip("/")
        or parts.query
        or parts.fragment
        or any(character.isspace() for character in endpoint)
    ):
        raise ValueError(
            "Marketplace environment variable 'AZURE_OPENAI_ENDPOINT' must be a bare Azure "
            "resource endpoint -- scheme and host only, with no path (such as "
            "'/openai'), query or fragment"
        )
    return endpoint


class AzureLLM(BaseLLM):  # type: ignore[misc]
    """Build a fresh Azure client from invocation-bound secrets for every call."""

    def __init__(self, *, tools: tuple[Any, ...] = ()) -> None:
        if tools:
            self._tools = tools

    def _client(self) -> BaseLLM:
        # This optional integration is absent from the repository's 1.0.1
        # development wheel. Keep only this provider-specific import lazy.
        from shared.services.llm.azure_openai_client import AzureOpenAIClient

        secrets = current_secrets()
        client = AzureOpenAIClient(
            {
                "api_key": secrets.require("AZURE_OPENAI_API_KEY"),
                "azure_endpoint": secrets.require("AZURE_OPENAI_ENDPOINT"),
                "azure_deployment": secrets.require("AZURE_OPENAI_DEPLOYMENT"),
            }
        )
        tools = getattr(self, "_tools", ())
        return client.bind_tools(list(tools)) if tools else client

    def complete(self, messages: list[Any]) -> dict[str, Any]:
        return cast(dict[str, Any], self._client().complete(messages))

    def stream(self, messages: list[Any]) -> Iterator[str]:
        yield from self._client().stream(messages)

    def bind_tools(self, tools: list[Any]) -> "AzureLLM":
        return type(self)(tools=tuple(tools))


def _marketplace_input_context() -> dict[str, str]:
    """Return the complete adapter-owned context admitted to agent State."""

    return {"channel": "marketplace", "locale": "ja-JP"}


class MarketplaceGraph(RetailPersonalisedOfferCopyAgent):
    """Marketplace-only context hardening and Azure dependency wiring."""

    def register_nodes(self) -> None:
        # The Marketplace runner compiles before provision_secrets(). The outer
        # graph snapshots config into PersonalisedOfferGraphNode during this
        # call, so install the credential-free lazy facade before that snapshot.
        self.config["llm"] = AzureLLM()
        super().register_nodes()

    def invoke(
        self,
        user_input: str,
        session_id: str = "",
        ctx: InvocationContext | None = None,
        input_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # Runner conversation history is untrusted free text outside this
        # agent's S-2 scan. Rebuild context exclusively from adapter constants.
        del input_context
        marketplace_ctx = replace(ctx, hitl_allowed=False) if ctx is not None else None
        return cast(
            dict[str, Any],
            super().invoke(
                user_input,
                session_id=session_id,
                ctx=marketplace_ctx,
                input_context=_marketplace_input_context(),
            ),
        )

    def provision_secrets(self, provider: SecretProvider) -> None:
        # Ignore the runner's broader dotenv-capable provider. This Pod may
        # resolve only the three Azure values it actually consumes.
        del provider
        environment_provider = _AllowlistedEnvironmentProvider()
        for key in _REQUIRED_SECRET_KEYS:
            _require_clean_secret(environment_provider, key)
        _require_azure_endpoint(environment_provider)
        super().provision_secrets(environment_provider)


def main() -> None:
    # Marketplace support is absent from AgentCore 1.0.1 and present in the
    # runner image, so importing it belongs strictly to the executable path.
    from shared.bootstrap import run_agent_marketplace

    run_agent_marketplace(
        MarketplaceGraph,
        agent_name=_AGENT_NAME,
        namespace=_NAMESPACE,
        config=load_agent_config(Path(__file__).resolve().parent),
    )


if __name__ == "__main__":
    main()
