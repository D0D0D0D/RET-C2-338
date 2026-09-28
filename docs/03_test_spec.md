# Test Specification — RET-C2-338

## Test Strategy
- 全 25 テスト pass（ローカル 1.0.0 wheel・`pytest tests/`）。
- 種別: Unit（各ノード）/ Integration（フルグラフ・fake LLM 注入）/ Proof-of-Boundary（S-1/S-2/S-3・import isolation・state safety）。
- LLM はテストで fake（`tests/conftest.py: FakeLLM`、`BaseLLM.complete` 互換）を `config["llm"]` 注入＝外部依存なし・hermetic。

## Framework Compliance Tests

| TC-ID | Test | Expected | Test file |
|-------|------|----------|-----------|
| TC-01 | State は flat TypedDict（Pydantic/credential なし） | CI の資格情報スキャン 0 / `test_state_safety` pass | tests/proof_of_boundary/test_state_safety.py |
| TC-06/07 | `_security_gate_*` を直接 override しない（`@final`） | FunctionNode 拡張は `_extra_*` のみ | src/nodes/* |
| TC-08 | `required_trust_level` 強制 | ANONYMOUS は S-1 で拒否し、PB-6 の `test_s1_denial_refuses_execution_before_execute` が `execute()` が呼ばれなかったことを証明する | tests/integration/test_security_boundary.py::TestS1TrustGate + tests/proof_of_boundary/test_pb_invoke_order.py |
| TC-09 | S-2 `_extra_security_gate_input()` 実装 | session-only 違反 reject | test_pre_process_node.py::test_s2_session_only_rejects_persistent_identifier |
| TC-10 | S-3 `_extra_security_gate_output()` 実装 | APPI 開示不在で raise（fail-closed） | test_post_process_node.py / test_security_boundary.py::TestS3APPIGate |
| TC-11 | S-4 各 execute で `emit_trace_event()` | 全ノードで 1 イベント以上 | src/nodes/*（lifecycle は framework 自動） |

## Proof-of-Boundary Tests

| PB-ID | Boundary | Expected | Test |
|-------|----------|----------|------|
| PB-2/5 | State serialization / checkpoint safety | primitives only・credential なし | test_state_safety.py |
| PB-4 | Import isolation | Level 0（agenticstar）import なし | test_import_isolation.py |
| PB-S1 | S-1 trust gate | ANONYMOUS 拒否 → status error | test_security_boundary.py::TestS1TrustGate |
| PB-S2 | S-2 session-only | persistent identifier → status error | test_security_boundary.py::TestS2SessionOnlyGate |
| PB-S3 | S-3 APPI fail-closed | 開示マーカー不在 → output block（status error） | test_security_boundary.py::TestS3APPIGate |

## Business Logic Tests

| BL-ID | Test | Input | Expected | Test |
|-------|------|-------|----------|------|
| BL-01 | パーソナライズ信号算出 | apparel 閲覧 + gold 会員 | PROMO-SUMMER + PROMO-GOLD eligible、cross_sell に補完カテゴリ商品 | test_inner_nodes.py::TestPersonalisationEngine |
| BL-02 | オファー生成 | signals + fake LLM | offer_copy/promo_copy を生成 | test_inner_nodes.py::TestRecommendationGenerate |
| BL-03 | cross-sell は決定論（LLM 由来でなく、価格エンジン非依存） | rogue LLM が価格付き item を返す | cross_sell は catalogue 由来のみ・price フィールドなし | test_inner_nodes.py::test_cross_sell_is_deterministic_not_from_llm |
| BL-04 | APPI 開示付与（冪等） | offer_copy | マーカー 1 回のみ付与・disclosure_attached=True | test_inner_nodes.py::TestAPPIDisclosure |
| BL-05 | フル E2E | verified ctx + session context | message に APPI マーカー、disclosure_attached、cross_sell | test_graph.py::test_happy_path_generates_offer_with_disclosure |

## Test Execution Summary
- 実行: ローカル venv（Python 3.11 + `agenticstar-agentcore==1.0.0`）
- Total 25 / Pass 25 / Fail 0 / Skip 0
- CI（`run-tests`）でも registry wheel install 後に同一スイートを実行。

## 実 LLM 1 回転検証（generation_mode: "llm" の実測）

`config/agent.yaml` は `generation_mode: "llm"` を宣言している。宣言が実装と一致することを
実 LLM で 1 回転させて確認した記録。テンプレートのコードは**修正不要**だった。

| 項目 | 内容 |
|---|---|
| 実施日 | 2026-08-20 |
| SDK | `agenticstar-agentcore==1.0.1` |
| 使用 LLM | Azure OpenAI（GPT-5 系デプロイ）の CLI クライアント（`BaseLLM` 実装を検証用に注入） |
| 注入シーム | `config["llm"]`（本番と同一。外側 `register_nodes()` の `_INNER_CONFIG_KEYS` 転送 → `PersonalisedOfferGraphNode` → 内側 `DomainWorkflowGraph` → `RecommendationGenerateNode`） |
| LLM 呼び出し回数 | **1**（`recommendation_generate` のみ） |
| 結果 | ✅ `status=success` / `degradation_reason` なし |
| 非空だった出力キー | `message`, `offer_copy`, `promo_copy`, `cross_sell`, `disclosure_attached` |
| 入力 | `case_payload` = `"夏物のおすすめは？"`、`live_input_context` = `session_input_context`（`test_graph.py::test_happy_path_generates_offer_with_disclosure` と同一） |

### 実 LLM でのみ確かめられたこと

- **プロンプトが出力契約を実際に導けている**: システムプロンプトが要求する
  `{"offer_copy": str, "promo_copy": str}` を実 LLM がそのまま返し、`_parse()` の
  JSON 経路で解釈された（フォールバックの「全文を offer_copy に入れる」経路ではない）。
  モックは常に整形済み JSON を返すため、この点は実 LLM でしか検証できない。
- **接地**: 応答は `eligible_promotions`（PROMO-SUMMER / PROMO-GOLD）と
  `related_items`（Linen Summer Shirt）だけを根拠にしており、存在しない商品・
  キャンペーンの捏造は無かった。
- **cross_sell は LLM 由来でない**: 実 LLM は cross_sell を返していないにもかかわらず、
  出力の `cross_sell` は catalogue + rules 由来の 2 件（FOOT-010 / ACCS-020）が入っている
  ＝ F-3 の決定論保証が実経路でも成立（BL-03 の設計意図どおり）。
- **APPI 開示**: `disclosure_attached=true`、`message` に開示マーカーが 1 回だけ付与された。
