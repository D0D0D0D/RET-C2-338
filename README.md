# RET-C2-338 — Retail Personalised Offer & Promo Copy Generator

> **Category**: Cat 2 (domain workflow)
> **Industry**: RET

## Overview

This agent writes the offer text and promotional copy a retail site shows a shopper, using only
what that shopper is doing in the current session — the categories they have browsed, what is in
their cart, their loyalty tier — together with the merchant's product catalogue and promotion
rules.

Three properties define it:

- **Session-only personalisation.** `personalisation_mode: session-only` is not a preference; the
  agent works from the per-request context and holds no cross-session profile. Context carrying a
  durable customer identifier is rejected rather than used.
- **Cross-sell is deterministic.** Complementary items are resolved from the catalogue and the
  promotion rules, never written by the language model, and never from a pricing engine. The model
  writes prose; it does not choose what is offered or assert a price.
- **The AI-recommendation disclosure is not configurable.** A dedicated node attaches the APPI
  2026 disclosure, and the output gate then verifies the marker is present in the message — if it
  is missing, the response is blocked outright rather than returned undisclosed. The
  `recommendation_disclosure: mandatory` key in the configuration is documentation of that fact;
  changing it does not switch the gate off.

This is an agent template built with the **AGENTIC STAR** development platform and the
**AgentCore Framework**. It is intended to be taken as a starting point: fork it, adapt it to
your own data and policies, and run it inside your own AGENTIC STAR deployment.

## Integration

Provide:

- an AgentCore runtime;
- your own product catalogue and promotion rules. The shipped
  `config/catalogue.sample.json` and `config/promotion_rules.sample.json` are samples for
  exercising the pipeline, not a starting dataset;
- a language model. This template differs from most in the family: it will construct a provider
  client itself if none is injected. `config["llm"]` remains the injection seam (and is what the
  tests use), but with nothing injected `build_llm()` builds the configured provider —
  Anthropic by default, with `openai` and `bedrock` also selectable via `llm_provider`;
- caller authentication in front of the entry adapter.

Runtime parameters read from `config/config.yaml` — **not** `config/agent.yaml`, which is the
static manifest (defaults in parentheses):

| Key | Meaning |
|---|---|
| `product_catalogue_path` (`config/catalogue.sample.json`) | Product catalogue JSON |
| `promotion_rules_path` (`config/promotion_rules.sample.json`) | Promotion rules JSON |
| `personalisation_mode` (`session-only`) | Restricts personalisation to the current request's context |
| `recommendation_disclosure` (`mandatory`) | Documentation of the disclosure requirement; the gate is enforced in code and cannot be disabled here |
| `system_prompt` | Brand-voice instruction for the copy. Intended to be edited |
| `max_retry` (`3`), `timeout_seconds` (`30`) | Framework retry routing and execution timeout |

### A note on the provider credential

`config/agent.yaml` declares `requires.extras: [anthropic]` but `requires.secrets: []`, and the
shipped code path builds the provider client from the node's configuration dictionary. The
provider client requires an `api_key` in that dictionary — it raises `ValueError` without one and
never reads the process environment — and nothing in this template puts one there. In practice a
deployment must **either** inject a ready `BaseLLM` through
`config["llm"]` — the path the tests exercise and the recommended one — **or** supply
`api_key` in the configuration passed to the graph, sourced from the platform's secret provider
(`ctx.secrets.require("ANTHROPIC_API_KEY")`), never from the process environment. Treat the
built-in provider construction as a convenience that still needs wiring, not as a working default.

## Requirements

**This template does not run standalone.** It requires:

| Requirement | Notes |
|---|---|
| **AGENTIC STAR platform** | The agent is written against the platform's runtime. Deployment guides and API documentation: [AGENTIC STAR Developers](https://developers.fd.agenticstar.tm.softbank.jp/) |
| **AgentCore Framework** (`agenticstar-agentcore`) | Supplied by the platform's own package registry at build time, with the `anthropic` extra. It is not published on public PyPI, so `pip install -e .` alone does not fetch it. |
| Python | >=3.11 |

```bash
pip install -e .
```

### Behaviour without the platform

The framework packages (`framework.*`, `shared.*`) must be importable — without them the process
fails at import, before any agent code runs. With them installed, the standalone server starts
without a platform connection and `GET /health` answers. An authenticated `/invoke` runs the
pipeline up to the generation node and then needs a working model client: with none injected and
no credential in the configuration, that node raises and the invocation ends as an error. Nothing
partially disclosed is returned — the output gate is on the same path.

## Input

`POST /invoke` on the standalone server takes `input` and `session_id` only — it deliberately
does **not** accept `input_context` from the request body. Personalisation context reaches the
agent from a gateway that calls `agent.invoke(..., input_context=...)` directly:

```json
{
  "channel": "web",
  "browsed_categories": ["apparel"],
  "cart_items": ["Canvas Sneakers"],
  "loyalty_tier": "gold"
}
```

```bash
curl -X POST http://127.0.0.1:8000/invoke \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer ${INVOKE_AUTH_TOKEN}" \
  -d '{"input": "夏物のおすすめは？", "session_id": "example-session"}'
```

Callers must be authenticated. The entry adapter starts every request at `ANONYMOUS` unless
upstream middleware stamps a verified trust level; when `INVOKE_AUTH_TOKEN` is set on the server
environment, a matching `Authorization: Bearer` header promotes the caller to
`VERIFIED_EXTERNAL`, and a non-matching one is rejected with **401**. A caller that is neither
middleware-verified nor token-authenticated is rejected with **401**; a caller whose verified
trust is below `VERIFIED_EXTERNAL` is rejected with **403**.

The Marketplace adapter discards the runner's `input_context` entirely and substitutes fixed,
adapter-owned values (`channel: marketplace`, `locale: ja-JP`), so runner conversation history,
any future runner key, and any customer segment or purchase history stay out of state.

## Output

```json
{
  "output": {
    "message": "夏物アパレルがおすすめです\n\n【AI提案・APPI2026】 …\n\n今だけ10%OFF\n\nあわせておすすめ: Canvas Sneakers",
    "offer_copy": "夏物アパレルがおすすめです\n\n【AI提案・APPI2026】 …",
    "promo_copy": "今だけ10%OFF",
    "cross_sell": [{"sku": "FOOT-010", "name": "Canvas Sneakers"}],
    "disclosure_attached": true
  },
  "status": "success"
}
```

`message` is the assembled customer-facing text; `offer_copy` and `promo_copy` are its parts, and
`cross_sell` is the deterministic complementary-item list. `disclosure_attached` reflects the
gate that has already run — a response missing the disclosure marker never reaches the caller.

Values above are illustrative; real output depends on the catalogue, the rules and the session
context.

## Security and Limitations

Every node requires verified-external trust, so an anonymous caller is stopped before any node
body runs. Only a msgpack-safe subset of the model response is written to state — the content,
the model name and the usage counts — never the raw provider object. Audit events carry a hashed
session identifier and counts, not the customer context or the generated text. The output gate is
fail-closed on the disclosure marker.

Known limitations:

- **No cross-session personalisation, by design.** The agent cannot use purchase history or a
  durable profile, and context containing a permanent customer identifier is rejected.
- **No real-time price, stock or delivery guarantees.** The copy must not assert them, and the
  agent has no source that could.
- **Offers are only as good as the configured data.** Eligible promotions and cross-sell
  candidates come entirely from the catalogue and rules files.
- **Malformed model output degrades to plain copy.** If the model does not return the expected
  JSON, the whole response is treated as the offer text and the promotional copy comes back
  empty. It is a degradation the caller can detect, but it is not signalled by `status`.

Output is machine-generated and assistive. It does not substitute for expert review, and any
customer-facing use should be checked against your own marketing and compliance policy.

## Release

- Version: 1.0.0
- Category: fixed multi-step domain workflow (Cat 2), inner workflow wrapped in a `GraphNode`
- Generation mode: `llm`
- HITL: not enabled
- Persistence: none — no checkpointer is configured, and none is wanted here
- External API clients: a provider client is constructed by the template when none is injected;
  Anthropic by default, with OpenAI and Bedrock selectable

## Quick Start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest tests/ -v
```

The suite runs with no platform connection and no network access: a fake `BaseLLM` is injected
through `config["llm"]`, so no provider client is ever constructed and no provider extra is
needed to run the tests.

## Documentation

`docs/02_design.md` carries the node flow, the personalisation-signal contract, the Marketplace
adapter boundary, and the disclosure gate design. `docs/03_test_spec.md` records the test
specification and the live-model verification run.

## Project Structure

```
src/          agent implementation (nodes, services, schemas)
tests/        unit, integration and boundary tests
config/       agent configuration
docs/         design and test specifications
```

See `docs/02_design.md` for the design and `docs/03_test_spec.md` for the test specification.

## Customising

1. Adjust `config/` for your own environment and policies.
2. Replace the knowledge sources and sample data with your own.
3. Review the node implementations under `src/nodes/` for domain-specific logic.
4. Re-run the test suite.

## License

MIT — see [LICENSE](LICENSE).

## Status of this repository

This template is published **as is**, by its individual author, under the MIT license. It carries
**no warranty and no support commitment**, and no organisation stands behind its behaviour or
fitness for any purpose. Issues and pull requests may or may not receive a response; that is at
the sole discretion of the repository owner.
