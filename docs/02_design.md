# Template Design Specification — RET-C2-338

> Retail Personalised Offer & Promo Copy Generator (APPI 2026 Compliant)
> Cat 2 / Industry RET / Pattern ChatAgent（L1 `AgentBaseGraph` 直接継承）。

## Position in AgentCore Architecture

- **Agent Class**: `RetailPersonalisedOfferCopyAgent`
- **L1 Base**: **AgentBaseGraph**（L1 を直接継承。ChatAgent は概念リファレンスで継承しない）
- **Composition**: Cat 2 = 外側 `AgentBaseGraph` + `main` スロットに `GraphNode`、内側に
  `DomainWorkflowGraph(BaseGraph)`（`src/graph/domain_workflow_graph.py`）
- **Three-Layer Separation**:
  - State: flat TypedDict 合成（Pydantic 不可 — msgpack 非互換）
  - Node: L1 継承（Template Method: `execute(self, state: AgentState) -> dict` のみ override、変更キーだけ返す）
  - Graph: composition（`register_nodes()` でノード差し込み、`add_edges()`/`route()` は override しない）

## Scope Boundary

### Staff-facing retrieval workflow との境界
| 観点 | Staff-facing retrieval workflow | **本件 RET-C2-338** |
|------|------------------|---------------------|
| 受け手 | 店舗スタッフ・運用者（staff-facing） | 顧客（customer-facing） |
| パターン | VectorRAGAgent（価格 KB・手順 KB の Q&A = **retrieval**） | ChatAgent（オファー文面の **generation**） |
| 入力 | 価格／手順ナレッジベース | セッション文脈 × 商品カタログ × 販促ルール |
| 出力 | スタッフ向け回答（根拠引用） | 顧客向けパーソナライズ訴求コピー ＋ APPI 開示 |
staff-facing retrieval workflow は運用者への情報提供、本件は顧客向け文面の生成を担うため、機能は重複しない。

### cross-sell は価格エンジン非依存
クロスセル提案は **商品カタログ＋販促ルールのみ**から生成する。外部のリアルタイム価格エンジンには一切依存しない。
catalogue に在庫・属性、promotion_rules に適用条件を持たせ、LLM はそこから訴求文を構成するだけで、価格算出ロジックを
持たない。この分離により、価格エンジンの有無にかかわらず同じ入力契約で利用できる。

## Architecture Overview

### Node Configuration（外側 backbone）

| Node | Responsibility | Input State | Output State | Inherits/Overrides |
|------|---------------|-------------|--------------|-------------------|
| initialize | schema_version / session_id / trust_level 設定 | — | session_id, caller_trust_level | InitializeNode (default) |
| pre_process | **InputParse**: user_input 検証・自由文からの PII ストリップ。S-2 で session-only 強制 | user_input, input_context | validated_input, enriched_context | `PreProcessNode(FunctionNode)` ＋ `_extra_security_gate_input()` |
| main | **PersonalisedOfferWorkflow**: 内側グラフ（context load→personalise→generate→APPI disclosure）を実行 | validated_input, input_context | offer_copy, promo_copy, cross_sell, disclosure_attached, result | `PersonalisedOfferGraphNode(GraphNode)` → inner `DomainWorkflowGraph` |
| post_process | **ResponseFormat**: 顧客向け最終メッセージ整形・response_metadata 構築。S-3 で **APPI 開示 presence ゲート** | offer_copy, promo_copy, cross_sell, disclosure_attached | formatted_output, response_metadata | `PostProcessNode(FunctionNode)` ＋ `_extra_security_gate_output()` |
| finalize | response_metadata / total_time_ms 構築 | — | response_metadata | FinalizeNode (default) |

### Inner DomainWorkflowGraph（`main` スロット内・`BaseGraph` 直接継承）

| Inner Node | Responsibility | 主な I/O | Security |
|------------|----------------|----------|----------|
| `customer_context_load` | セッション限定文脈（browsed_categories / cart_items / loyalty_tier）を input_context からロード。**cross-session PII 永続化なし** | input_context → session_context | S-4 event（anonymised session id） |
| `personalisation_engine` | session_context × product_catalogue × promotion_rules から決定的に適用可能 promo・関連カテゴリ・ランク特典を算出 | session_context, (catalogue, rules via Service) → personalisation_signals | S-4 event |
| `recommendation_generate` | LLM が訴求コピー＋販促文＋**クロスセル（カタログ＋ルールのみ由来）**を生成 | personalisation_signals, system_prompt → offer_copy, promo_copy, cross_sell | S-4 event（recommendation category, timestamp） |
| `appi_disclosure` | **非設定可能**の APPI 2026 AI レコメンド開示文を生成内容へ付与。`disclosure_attached=True` | offer_copy/promo_copy → (+ disclosure), disclosure_attached | hard-coded 開示文 |

inner topology は線形: `START → customer_context_load → personalisation_engine → recommendation_generate → appi_disclosure → END`。
`get_output()` が `{output, status, ...}` を返し、外側 `merge_output()` が outer state（offer_copy/promo_copy/cross_sell/disclosure_attached/result/status）へマップする。

### Data Flow

```
START → initialize → pre_process → main(GraphNode) → {route} → post_process → finalize → END
                                        ↓ (retry, max 3)
                                     pre_process

main 内部 (DomainWorkflowGraph):
  START → customer_context_load → personalisation_engine → recommendation_generate → appi_disclosure → END
```

### State Definition（`State(AgentState)` 追加フィールドのみ）

| Field | Type | Purpose | Required |
|-------|------|---------|----------|
| `session_context` | `dict` | セッション限定文脈（browsed_categories, cart_items, loyalty_tier）。**永続化しない** | Yes |
| `personalisation_signals` | `dict` | 適用 promo / 関連カテゴリ / ランク特典 | Yes |
| `offer_copy` | `str` | 生成されたオファー文面 | Yes |
| `promo_copy` | `str` | 生成された販促コピー | Yes |
| `cross_sell` | `list` | クロスセル提案（カタログ＋ルール由来） | No |
| `disclosure_attached` | `bool` | APPI 開示付与済みフラグ（S-3 ゲートの検証対象） | Yes |

共有フィールド（user_input, validated_input, status, session_id, node_history, error_log, result,
formatted_output, response_metadata 等）は `AgentState` から継承。

**State Constraints (mandatory):**
- flat TypedDict のみ（プリミティブ＋ JSON シリアライズ可能型）
- JWT / API キー / 資格情報を State に置かない（checkpoint DB 漏洩防止）
- InvocationContext は `config["configurable"]` 経由のみ（State に入れない）
- Pydantic / dataclass / 任意 Python オブジェクト不可（msgpack 非互換）
- `session_context` は cross-session で永続化せず、セッション終了時にクリア（S-4 分離）

## Framework Utilization

## Security Model（S-1〜S-5 — 5層）

> 以下では、最小 trust level とディスクレーマー強制の実装箇所を明示する。

| 層 | 実装箇所 | 内容 |
|----|----------|------|
| **S-1 trust gate** | 全ノード `required_trust_level`（`BaseNode.__call__` 自動強制） | **最小要求 = `TrustLevel.VERIFIED_EXTERNAL`**（下記根拠） |
| **S-2 input gate** | `PreProcessNode._extra_security_gate_input()` | 既定 PII scan の後、自由文 PII ストリップ確認 ＋ **session-only 強制**（cross-session プロファイル識別子があれば `status=error` で reject） |
| **S-3 output gate** | `PostProcessNode._extra_security_gate_output()` | 既定 credential scan の後、**APPI 2026 開示 presence ゲート（非設定可能・fail-closed）**。開示マーカー不在なら raise |
| **S-4 audit/trace** | 各 inner `execute()` 内 `emit_trace_event()` | ドメインイベントを 1 つ以上（anonymised session id / recommendation category / timestamp）。node_start/complete/error は framework 自動 emit のため重複させない |
| **S-5 disclaimer ＋ 監査記録** | ①`appi_disclosure` ノードが付与 → `PostProcessNode` S-3 で検証 ／ ②recommendation 監査ログ | 下記参照 |

### S-1 最小 trust_level の根拠
- **採用値 = `VERIFIED_EXTERNAL`**。有効 enum は `ANONYMOUS` / `VERIFIED_EXTERNAL` / `INTERNAL` の 3 値のみ（str enum・int 比較不可）。
- 本エージェントは **customer-facing**。顧客はロイヤルティ会員として**認証済みの外部ユーザー**であり、会員ランク等の PII を扱うため
  `ANONYMOUS` では不十分 → 最小 `VERIFIED_EXTERNAL`。
- `INTERNAL` はスタッフ／サービス向けで、これを要求すると**全ての顧客リクエストを S-1 で拒否**してしまう（staff-facing は別のワークフローで扱う）。
  よって `INTERNAL` は不適。customer-facing の正しい最小レベルは `VERIFIED_EXTERNAL`。

### S-5 ディスクレーマー実装箇所
- **AI 生成コンテンツのディスクレーマー = APPI 2026 AI レコメンド開示**そのもの。これが「本オファーは AI 生成」である旨を顧客に明示する。
  - **付与箇所**: inner `appi_disclosure` ノード（hard-coded・非設定可能）。
  - **検証箇所**: `PostProcessNode._extra_security_gate_output()`（S-3）で presence を fail-closed 検証。不在出力は顧客に届かない。
- **monitoring/accountability の監査記録**: recommendation 監査ログ（匿名化セッション ID・推薦カテゴリ・タイムスタンプ）を
  `recommendation_generate` の S-4 `emit_trace_event()` として記録（S-5 の説明責任面）。

### Shared Components Used
- [x] InvocationContext（correlation_id, session_id, caller_trust_level, hitl_allowed）
- [x] **S-1 / S-2 / S-3 / S-4 / S-5**: 上記 Security Model 表のとおり

> **S-2/S-3 gate behaviour by node type (ADR-017):**
> - `FunctionNode` subclass（pre_process / post_process）→ framework `@final` gate が自動実行。
>   拡張は `_extra_security_gate_input()` / `_extra_security_gate_output()` のみ（`_security_gate_*` 直 override は `TypeError`）
> - `GraphNode`（main）→ deliberate no-op（内側ノードのゲートが適用済み）

### APPI 開示ゲートの二重防御（S-3 CRITICAL）
1. `appi_disclosure` ノードが開示文を付与（do-it）。
2. `PostProcessNode._extra_security_gate_output()` が開示マーカー存在を検証（verify, fail-closed・非設定可能）。
不在なら raise → `BaseNode.__call__` が status:error 化。`recommendation_disclosure: mandatory` は config に記すが
**強制はコード側**（config で無効化できない）。

> **規制文言の確認**: リリース前に、APPI 2026 三年見直し（2026-07-06）の確定結果と hard-coded 開示文言の整合を
> 確認し、必要に応じて文言を更新する。

### LLM / Service / Secrets
- LLM は `src/services/llm_client.py`（注入シーム）経由（`framework.llm` 非搭載のため自前化し、wheel 統合テストで確認）。
- `src/services/service.py` が product_catalogue（`product_catalogue_path`）と promotion_rules を読む。business logic は持たない。
- secrets は `bound_secrets` + `shared.secrets.factory`（`os.environ` 直読み禁止）。

## AGENTIC STAR Marketplace Entry Adapter

リポジトリ直下の `cli.py` は Marketplace 専用の `MarketplaceGraph` を提供する。runner が渡す
`input_context` はマージせず破棄し、State へは adapter 所有の固定値
`{"channel": "marketplace", "locale": "ja-JP"}` だけを渡す。`PreProcessNode` が両値を読み、特に
`locale` の既定値も `ja-JP` だが、Marketplace 由来であることを監査イベント上明示するため `channel` も含めて固定する。
runner の `conversation_history`、将来追加される runner key、顧客セグメントや購買履歴は State に入らない。

外側 `PersonalisedOfferGraphNode.extract_input()` は outer State の `input_context` 全体を inner user input の
`session_context` へ直列化する。このため adapter での再構築は inner graph にもそのまま効き、
`CustomerContextLoadNode` が抽出する `browsed_categories` / `cart_items` は空、`loyalty_tier` は `none` となる。
Marketplace 経路が既存経路以外の PII を追加することはない。

Marketplace の LLM は `AzureLLM` facade に固定する。facade は接続値を保持せず、`complete()` / `stream()` ごとに
`current_secrets()` から3値を解決して新しい `AzureOpenAIClient` を作る。runner のライフサイクルは
`compile()` の後に `provision_secrets()` を呼ぶため、`MarketplaceGraph.register_nodes()` は
`super().register_nodes()` より前に facade を `config["llm"]` へ置く。これにより outer graph が作る
`inner_config` のスナップショットと、inner `RecommendationGenerateNode(llm=...)` の双方へ確実に到達する。

`provision_secrets()` は runner の dotenv 対応 provider を破棄し、次の環境変数だけを公開する allowlist provider
へ差し替える。未設定、空、空白のみ、前後空白、CR/LF 混入は起動時に fail closed とする。

- `AZURE_OPENAI_API_KEY`
- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_DEPLOYMENT`

scope gate は置かない。`src/api/server.py::_ctx()` の既存 scope note のとおり、この template は
「NO scope model」であり、`authenticate_scope()` を強制すると「gate on a scope nothing consumes」となるためである。
`STG_DEFAULT_COMPANY_ID` / `STG_DEFAULT_PROJECT_ID` は要求せず、fail closed の対象を、この AG が実際に消費する
Azure 3値へ振り替える。また、グラフ、ノード、service には write / ingest / feedback / resume の operation mode や
永続化処理がなく、読み取り専用の生成フローなので Marketplace 用モードゲートは新設しない。

## Import Isolation Confirmation
- [x] agenticstar-platform SDK（Level 0）を import しない
- [x] import 対象は framework/ と shared/ のみ（agents/base/ 不要）

## Design Decision Record

| Decision | Option A | Option B | Chosen | Rationale |
|----------|----------|----------|--------|-----------|
| L1 base type | AgentBaseGraph | AutonomousBaseGraph | **AgentBaseGraph** | 固定多段ワークフロー。自律ループ不要 |
| Composition pattern | Standalone（単一ノード列） | GraphNode（subgraph） | **GraphNode (subgraph)** | Cat 2 = 内側 domain workflow を `main` に内包する標準形 |
| Error propagation | propagate | handle | **propagate** | 内側エラーは `SubgraphError` で fail-fast（販促文の不正生成を黙って通さない） |
| APPI 開示強制 | config フラグ | コード（S-3 ゲート + ノード二重防御） | **コード（非設定可能）** | 規制要件。config で無効化させない compliance-by-construction |
| cross-sell ソース | 価格エンジン連携 | カタログ＋販促ルールのみ | **カタログ＋ルールのみ** | 外部価格エンジンへの依存を避ける |
