"""AGENTIC STAR Marketplace adapter boundary and Azure wiring tests."""

from __future__ import annotations

import subprocess
import sys
from types import ModuleType

import pytest
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel
from framework.secrets.base import NullProvider
from framework.secrets.context import bound_secrets

import cli
from src.constants import APPI_DISCLOSURE_MARKER
from tests.conftest import CATALOGUE, RULES


def _set_azure_environment(monkeypatch, suffix: str = "one") -> dict[str, str]:
    values = {key: f"test-{suffix}-{key.lower()}" for key in cli._REQUIRED_SECRET_KEYS}
    # The startup gate requires a bare Azure resource endpoint, so
    # this value cannot be a placeholder like the other secrets.
    values["AZURE_OPENAI_ENDPOINT"] = f"https://{suffix}.services.ai.azure.example"
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return values


def _install_fake_azure_module(monkeypatch, clients: list) -> None:
    class FakeAzureOpenAIClient:
        def __init__(self, config):
            self.config = dict(config)
            self.calls = []
            clients.append(self)

        def complete(self, messages):
            self.calls.append(messages)
            return {
                "content": '{"offer_copy":"Azure 経由のおすすめ","promo_copy":"期間限定です"}',
                "model": self.config["azure_deployment"],
                "usage": {},
            }

        def stream(self, messages):
            del messages
            yield "ok"

        def bind_tools(self, tools):
            del tools
            return self

    module = ModuleType("shared.services.llm.azure_openai_client")
    module.AzureOpenAIClient = FakeAzureOpenAIClient
    monkeypatch.setitem(sys.modules, module.__name__, module)


def test_cli_imports_with_agentcore_1_0_1():
    completed = subprocess.run(
        [sys.executable, "-c", "import cli; print(cli.MarketplaceGraph.__name__)"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "MarketplaceGraph"


def test_invoke_rebuilds_state_context_without_runner_history():
    sentinel = "UNSCANNED-CONVERSATION-PII-338"
    agent = cli.MarketplaceGraph()
    agent.compile()
    captured = {}

    def capture_state(initial_state, config=None):
        del config
        captured.update(initial_state)
        return {**initial_state, "status": "success", "formatted_output": {"message": "ok"}}

    agent._compiled.invoke = capture_state
    original_ctx = InvocationContext(
        caller_id="marketplace-user",
        caller_trust_level=TrustLevel.VERIFIED_EXTERNAL,
        hitl_allowed=True,
    )
    result = agent.invoke(
        "おすすめを教えて",
        ctx=original_ctx,
        input_context={
            "conversation_history": [{"role": "user", "content": sentinel}],
            "loyalty_tier": sentinel,
            "future_runner_key": sentinel,
        },
    )

    assert captured["input_context"] == {"channel": "marketplace", "locale": "ja-JP"}
    assert sentinel not in repr(captured)
    assert sentinel not in repr(result)
    assert captured["hitl_allowed"] is False


@pytest.mark.parametrize("missing_key", cli._REQUIRED_SECRET_KEYS)
def test_missing_azure_secret_fails_during_provision(monkeypatch, missing_key):
    _set_azure_environment(monkeypatch)
    monkeypatch.delenv(missing_key)

    with pytest.raises(ValueError, match=missing_key):
        cli.MarketplaceGraph().provision_secrets(NullProvider())


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://example.cognitiveservices.azure.com/openai/responses?api-version=2025-04-01-preview",
        "https://example.services.ai.azure.example/openai",
        "https://example.services.ai.azure.example/v1",
        "https://example.services.ai.azure.example?api-version=2024-10-21",
        "example.services.ai.azure.example",
    ],
    ids=["api-path", "openai-path", "base-path", "query-only", "missing-scheme"],
)
def test_unusable_azure_endpoint_shape_fails_during_startup(monkeypatch, endpoint):
    """AzureOpenAIClient appends its own path, so anything but a bare endpoint breaks.

    The resulting error surfaces inside complete(); a node that swallows it
    degrades silently while the invocation still reports status: success, so the
    adapter has to reject the shape at startup instead.
    """

    _set_azure_environment(monkeypatch)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", endpoint)

    with pytest.raises(ValueError, match="bare"):
        cli.MarketplaceGraph().provision_secrets(NullProvider())


@pytest.mark.parametrize("secret_key", cli._REQUIRED_SECRET_KEYS)
@pytest.mark.parametrize("invalid", ["", "   ", "value\nnext", "value\rnext"])
def test_invalid_azure_secret_fails_during_provision(monkeypatch, secret_key, invalid):
    _set_azure_environment(monkeypatch)
    monkeypatch.setenv(secret_key, invalid)

    with pytest.raises(ValueError, match=secret_key):
        cli.MarketplaceGraph().provision_secrets(NullProvider())


def test_provisioned_provider_is_environment_only_and_allowlisted(monkeypatch):
    expected = _set_azure_environment(monkeypatch)
    monkeypatch.setenv("UNRELATED_PLATFORM_SECRET", "must-not-be-visible")
    agent = cli.MarketplaceGraph()

    agent.provision_secrets(NullProvider())

    provider = agent._secrets_provider
    assert {key: provider.require(key) for key in cli._REQUIRED_SECRET_KEYS} == expected
    assert provider.get("UNRELATED_PLATFORM_SECRET") is None


def test_full_graph_invoke_reaches_lazy_azure_client_after_compile_then_provision(monkeypatch):
    _set_azure_environment(monkeypatch)
    clients = []
    _install_fake_azure_module(monkeypatch, clients)
    agent = cli.MarketplaceGraph({"catalogue": CATALOGUE, "promotion_rules": RULES})

    # This is the deployed runner order. Moving Azure injection after the
    # super().register_nodes() snapshot makes this test miss the fake client.
    agent.compile()
    agent.provision_secrets(NullProvider())
    ctx = InvocationContext(caller_trust_level=TrustLevel.VERIFIED_EXTERNAL)
    with bound_secrets(agent._secrets_provider):
        result = agent.invoke("夏物のおすすめは？", ctx=ctx)

    assert len(clients) == 1
    assert len(clients[0].calls) == 1
    assert "Azure 経由のおすすめ" in result["output"]["message"]
    assert APPI_DISCLOSURE_MARKER in result["output"]["message"]


def test_azure_llm_resolves_fresh_values_and_client_for_every_call(monkeypatch):
    clients = []
    _install_fake_azure_module(monkeypatch, clients)
    provider = cli._AllowlistedEnvironmentProvider()
    llm = cli.AzureLLM()
    assert vars(llm) == {}

    with bound_secrets(provider):
        first = _set_azure_environment(monkeypatch, "first")
        llm.complete([{"role": "user", "content": "first"}])
        second = _set_azure_environment(monkeypatch, "second")
        llm.complete([{"role": "user", "content": "second"}])

    assert len(clients) == 2
    assert clients[0].config == {
        "api_key": first["AZURE_OPENAI_API_KEY"],
        "azure_endpoint": first["AZURE_OPENAI_ENDPOINT"],
        "azure_deployment": first["AZURE_OPENAI_DEPLOYMENT"],
    }
    assert clients[1].config == {
        "api_key": second["AZURE_OPENAI_API_KEY"],
        "azure_endpoint": second["AZURE_OPENAI_ENDPOINT"],
        "azure_deployment": second["AZURE_OPENAI_DEPLOYMENT"],
    }
    assert vars(llm) == {}


def test_main_defers_marketplace_import_and_loads_repo_config(monkeypatch):
    called = {}

    def fake_runner(agent_cls, **kwargs):
        called["agent_cls"] = agent_cls
        called.update(kwargs)

    module = ModuleType("shared.bootstrap")
    module.run_agent_marketplace = fake_runner
    monkeypatch.setitem(sys.modules, module.__name__, module)

    cli.main()

    assert called["agent_cls"] is cli.MarketplaceGraph
    assert called["agent_name"] == "RET-C2-338"
    assert called["namespace"] == "ret"
    assert called["config"]["max_retry"] == 3
