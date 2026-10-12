# Case gereksinimleri kapsama tablosu

Her case maddesi, repoda onu karşılayan kod, rapor veya dokümanla eşlenmiştir. Yalnızca repoda gerçekten
bulunan dosyalar yazıldı. `*.parquet`, `artifacts/` ve `data/processed/` `.gitignore`'dadır: bu dosyalar
temiz klonda yoktur, `make pipeline` ile üretilir. Tabloda bunlar "(parquet, üretilir)" diye işaretlidir.

Son güncelleme: K-52 ... K-56 sonrası (outlier CSV, "user" feature eşlemesi, örnek fraud politikası, FeatureAgent, C4/R10'da addr1 dolu koşulu; z-skoru std tabanı bilinen sınır olarak kayıtlı).
Tüm maddeler **tam**.

Durum: **tam** = madde doğrudan karşılanıyor; **kısmi** = karşılanıyor ama ayrı/açık bir çıktısı veya
adlandırması eksik; **yok** = repoda karşılığı yok.

## Adım 1 - Veri birleştirme ve kalite

| Adım | Case maddesi | Karşılayan dosya / fonksiyon / rapor | Kısa açıklama | Durum |
|---|---|---|---|---|
| 1 | Birleştirme | [`src/data/loader.py`](../src/data/loader.py) `load_merged`, `load_data`; [step1.md](step1.md); [summary.md](../reports/profile/summary.md) "Join" | `TransactionID` ile LEFT JOIN, `has_identity` bayrağı, etiket ayrı `y` | tam |
| 1 | Eksik veri analizi | [`src/profiling/quality.py`](../src/profiling/quality.py) `missing_table`, `group_missing`; [group_missing.csv](../reports/profile/group_missing.csv); [null_by_group.png](../reports/figures/null_by_group.png); [technical_doc.md §4.3](technical_doc.md#43-eksik-veri) | Kolon ve grup bazında null oranı | tam |
| 1 | Kolon tiplerini otomatik belirleme | [`src/profiling/schema.py`](../src/profiling/schema.py) `infer_type`, `infer_schema`; [column_schema.csv](../reports/profile/column_schema.csv) | Kural tabanlı tip çıkarımı: numeric / categorical / datetime / id / flag | tam |
| 1 | Veri kalite analizi | [`src/profiling/quality.py`](../src/profiling/quality.py) `quality_checks`; [quality_checks.csv](../reports/profile/quality_checks.csv); [summary.md](../reports/profile/summary.md) "Kalite bulgulari" | Tekrar eden satır/ID, yüksek null'lı kolon, negatif değer, sıfır/negatif tutar | tam |
| 1 | Kolon dağılımları | [`src/profiling/distributions.py`](../src/profiling/distributions.py) `numeric_distributions`, `categorical_topn`; `distributions.parquet`, `categorical_topn.parquet` (parquet, üretilir); [amount_log.png](../reports/figures/amount_log.png); [docs/eda.md](eda.md) + [reports/eda/](../reports/eda/) | Sayısal özet istatistikler, kategorik top-N, EDA grafikleri | tam |
| 1 | Yüksek cardinality | [`src/profiling/schema.py`](../src/profiling/schema.py) `cardinality_class`; [summary.md](../reports/profile/summary.md) "Yuksek cardinality"; [technical_doc.md §4.4](technical_doc.md#44-yüksek-cardinality); `freq_*` feature'ları ([feature_catalog.csv](../reports/features/feature_catalog.csv)) | Cardinality sınıfı; one-hot yok, frequency encoding | tam |

## Adım 2 - Profiling

| Adım | Case maddesi | Karşılayan dosya / fonksiyon / rapor | Kısa açıklama | Durum |
|---|---|---|---|---|
| 2 | Numeric / categorical / datetime ayrımı | [`src/profiling/schema.py`](../src/profiling/schema.py) `infer_type`; [column_schema.csv](../reports/profile/column_schema.csv); [summary.md](../reports/profile/summary.md) "Tip dagilimi" | Tip + `type_source` (kural / sözlük) | tam |
| 2 | Null ratio | [`src/profiling/quality.py`](../src/profiling/quality.py) `missing_table`; `missing.parquet` (parquet, üretilir); [group_missing.csv](../reports/profile/group_missing.csv) | Kolon bazında null oranı | tam |
| 2 | Outlier analizi | [`src/profiling/distributions.py`](../src/profiling/distributions.py) `outlier_row`, `outlier_table`; [outliers.csv](../reports/profile/outliers.csv) (+ parquet); [step2.md "Bulgular"](step2.md) | Sayısal kolon başına IQR çitleri + robust z (MAD) aykırı sayısı ve oranı; TransactionAmt ham ve log1p (K-52) | tam |
| 2 | Distribution analizi | [`src/profiling/distributions.py`](../src/profiling/distributions.py) `numeric_distributions`; `distributions.parquet` (parquet, üretilir); [step2.md "Bulgular"](step2.md) | skew, kurtosis, q01..q99 (fit kümesi) | tam |
| 2 | Rare categorical combination analizi | [`src/profiling/distributions.py`](../src/profiling/distributions.py) `rare_combinations`; [rare_summary.csv](../reports/profile/rare_summary.csv); `rare_categories.parquet` (parquet, üretilir) | (card4,card6,ProductCD), (P,R emaildomain), (DeviceType,DeviceInfo) + tek kolonlar; eşik 1e-4 | tam |
| 2 | Kolon ilişkileri | [`src/profiling/relations.py`](../src/profiling/relations.py) `spearman_pairs`, `cramers_pairs`, `redundancy_clusters`; [redundancy_clusters.csv](../reports/profile/redundancy_clusters.csv); `column_relations.parquet` (parquet, üretilir) | Spearman, Cramér's V, V kolonu kümeleri | tam |
| 2 | Entity davranış patternleri | [`src/profiling/entity.py`](../src/profiling/entity.py) `compare_candidates`, `d1n_constancy`; [entity_patterns.csv](../reports/profile/entity_patterns.csv); [d1n_constancy.csv](../reports/profile/d1n_constancy.csv); [entity_size_distribution.png](../reports/figures/entity_size_distribution.png); [step2.md](step2.md) | 10 entity adayının karşılaştırması, karar K-05 | tam |

## Adım 3 - Feature engineering

| Adım | Case maddesi | Karşılayan dosya / fonksiyon / rapor | Kısa açıklama | Durum |
|---|---|---|---|---|
| 3 | Temporal (hour, day_of_week, is_weekend) | [`src/features/timecal.py`](../src/features/timecal.py) `calendar_features`; [feature_catalog.csv](../reports/features/feature_catalog.csv) (grup `temporal`, 10 kolon) | `hour`, `day_of_week`, `is_weekend`, `is_business_hours`, `local_hour_est`, `holiday_season` ... | tam |
| 3 | Entity (user_avg_amount, user_transaction_count vb.) | [`src/features/history.py`](../src/features/history.py) `batch_history`, `EntityStore`; [feature_catalog.csv](../reports/features/feature_catalog.csv) (grup `entity`, 24 kolon); eşleme tablosu: [step3.md "Case'teki user feature'larının karşılığı"](step3.md), [technical_doc.md §5.1](technical_doc.md#51-featurelar-adım-3), [feature_dictionary.md](../knowledge_base/feature_dictionary.md) | user_avg_amount = `ent_avg_amt`, user_transaction_count = `ent_txn_count`, + `ent_std_amt`, velocity `ent_cnt_*`/`ent_sum_*`; "user" = entity proxy card1+addr1 (kart grubu, kişi değil) (K-52) | tam |
| 3 | Relational | [`src/features/rowwise.py`](../src/features/rowwise.py) `row_features`; [feature_catalog.csv](../reports/features/feature_catalog.csv) (grup `relational`, 7 kolon) | `card_new_addr`, `device_ent_match`, `has_recipient`, `email_mismatch`, `foreign_addr2`, `addr2_missing`, `os_browser_rare` | tam |
| 3 | Context feature'lar | [`src/features/rowwise.py`](../src/features/rowwise.py) `row_features`; [feature_catalog.csv](../reports/features/feature_catalog.csv) (grup `context`, 21 kolon) | Tutar biçimi, `has_identity`, `dist*`, `freq_*` | tam |

## Adım 4 - Anomali katmanları

| Adım | Case maddesi | Karşılayan dosya / fonksiyon / rapor | Kısa açıklama | Durum |
|---|---|---|---|---|
| 4 | Column anomali | [`src/detection/column.py`](../src/detection/column.py) `ColumnDetector` | ECDF kuyruk skoru, top-3 kolon (K-12) | tam |
| 4 | Multivariate anomali | [`src/detection/multivariate.py`](../src/detection/multivariate.py) `MultivariateDetector` | Isolation Forest, seed 42 (K-13) | tam |
| 4 | Entity anomali | [`src/detection/entity.py`](../src/detection/entity.py) `EntityDetector` | Entity'ye göre sapma + global geri çekme (K-14) | tam |
| 4 | Temporal anomali | [`src/detection/temporal.py`](../src/detection/temporal.py) `TemporalDetector` | Beş alt skor: velocity, inter-arrival, düşük hacim, saat nadirliği, hacim sapması (K-15) | tam |
| 4 | Skorların ayrı ayrı üretilmesi | [`src/scoring/service.py`](../src/scoring/service.py) `ScoringService.layer_scores`; `layer_scores.parquet` (parquet, üretilir); [holdout_metrics.csv](../reports/scores/holdout_metrics.csv); [step4.md](step4.md) | Her katman için `raw_<layer>` ve `<layer>_score` ayrı kolon; katman bazlı metrikler | tam |

## Adım 5 - Skor birleştirme

| Adım | Case maddesi | Karşılayan dosya / fonksiyon / rapor | Kısa açıklama | Durum |
|---|---|---|---|---|
| 5 | Normalize | [`src/detection/normalization.py`](../src/detection/normalization.py) `QuantileNormalizer` | Fit kuantil tablosu ile [0,1] (K-16) | tam |
| 5 | Weighted aggregation | [`src/scoring/aggregation.py`](../src/scoring/aggregation.py) `WeightedAverage`; [`configs/weights.yaml`](../configs/weights.yaml) | 0,35 / 0,25 / 0,20 / 0,20 (K-17) | tam |
| 5 | Final raw score | [`src/scoring/service.py`](../src/scoring/service.py) `score_batch` (`raw_anomaly_score`, `anomaly_score_norm`); [step5.md](step5.md) | Ham toplam ve normalize toplam ikisi de saklanır | tam |
| 5 | Yöntemin neden seçildiği | [technical_doc.md §5.3](technical_doc.md#53-normalizasyon-ve-birleştirme-adım-5); [ablation.csv](../reports/scores/ablation.csv); [corr_weights.csv](../reports/scores/corr_weights.csv); [decisions.md](decisions.md) K-16, K-17 | Max, noisy-OR, korelasyon ağırlıklı alternatiflerle karşılaştırma | tam |

## Adım 6 - Context Adjust

| Adım | Case maddesi | Karşılayan dosya / fonksiyon / rapor | Kısa açıklama | Durum |
|---|---|---|---|---|
| 6 | Business hours context | [`configs/context.yaml`](../configs/context.yaml) C1 `business_hours_known_entity`; [`src/context/engine.py`](../src/context/engine.py) `ContextAdjustEngine` | Yerel 09-18, hafta içi, geçmişi olan entity: x0,90 | tam |
| 6 | Weekend adjustment | [`configs/context.yaml`](../configs/context.yaml) C3 `weekend_established_entity` | Hafta sonu + en az 5 önceki işlem: x0,95 | tam |
| 6 | Trusted entity adjustment | [`configs/context.yaml`](../configs/context.yaml) C4 `trusted_entity`; [c4_coverage.csv](../reports/context/c4_coverage.csv) | Uzun geçmiş + normal tutar + bilinen cihaz ve e-posta + addr1 dolu (K-55: adresi boş kart grupları güvenilir sayılmaz): x0,75 | tam |
| 6 | False positive azaltımı (önce/sonra metrik) | [fp_comparison.csv](../reports/context/fp_comparison.csv); [fp_impact.csv](../reports/context/fp_impact.csv); [ablation.csv](../reports/context/ablation.csv); [technical_doc.md §6.4](technical_doc.md#64-false-positive-etkisi-ve-kural-bazlı-ablation), [§8](technical_doc.md#8-önce--sonra-false-positive-tablosu) | Holdout'ta %1 / %5 bütçede FP, precision, recall; kural bazlı ablation; A1 (K-55) sonrası satırları eklendi, öncekiler korundu | tam |
| 6 | Kendi context kurallarımız ve dokümantasyonu | [`configs/context.yaml`](../configs/context.yaml) C2, C5, C6a/b, C7, C8, C9a/b, G1; [step6.md](step6.md); [technical_doc.md §6.2](technical_doc.md#62-kurallar-parametreler-ve-gerekçeler); [context_cards.md](../knowledge_base/generated/context_cards.md) | Her kuralda koşul, çarpan, `rationale` | tam |

## Adım 7 - Rule Engine

| Adım | Case maddesi | Karşılayan dosya / fonksiyon / rapor | Kısa açıklama | Durum |
|---|---|---|---|---|
| 7 | JSON/YAML configurable engine | [`configs/rules.yaml`](../configs/rules.yaml), [`configs/rules_extra.json`](../configs/rules_extra.json); [`src/rules/repository.py`](../src/rules/repository.py) `RuleRepository`, `validate_rules` | YAML + JSON yükleme, `reload()`, istekte gelen kural seti | tam |
| 7 | If-then | [`src/rules/conditions.py`](../src/rules/conditions.py) `evaluate_condition`; [`src/rules/engine.py`](../src/rules/engine.py) `RuleEngine` | Koşul DSL'i -> action (block / review / allow / boost) | tam |
| 7 | Priority | [`src/rules/resolver.py`](../src/rules/resolver.py) `sort_key`; `priority` alanı ([rules.yaml](../configs/rules.yaml)) | Öncelik -> önem -> aksiyon sırası | tam |
| 7 | Conflict resolution | [`src/rules/resolver.py`](../src/rules/resolver.py) `resolve`, `resolve_score_over_allow`; [conflicts.csv](../reports/rules/conflicts.csv); [conflict_examples.json](../reports/rules/conflict_examples.json); [technical_doc.md §7.3](technical_doc.md#73-öncelik-ve-conflict-resolution) | Kazanan kural + `suppressed_rules` gerekçesiyle | tam |
| 7 | Explainability | [`src/rules/explain.py`](../src/rules/explain.py) `render_message`; [technical_doc.md §7.4](technical_doc.md#74-explainability-çıktısı) | `triggered_rules`, `reasons` (gerçek değerlerle), `decision_source` | tam |
| 7 | En az 8-10 kural | [`configs/rules.yaml`](../configs/rules.yaml) R01-R10, [`configs/rules_extra.json`](../configs/rules_extra.json) R11-R12; [rule_metrics.csv](../reports/rules/rule_metrics.csv) | 12 kural | tam |

## Adım 8 - RAG

| Adım | Case maddesi | Karşılayan dosya / fonksiyon / rapor | Kısa açıklama | Durum |
|---|---|---|---|---|
| 8 | Knowledge base (örnek fraud policy / kural dokümanları) | [fraud_policy.md](../knowledge_base/fraud_policy.md), [typologies.md](../knowledge_base/typologies.md), [operations_guide.md](../knowledge_base/operations_guide.md), [feature_dictionary.md](../knowledge_base/feature_dictionary.md), [rule_cards.md](../knowledge_base/generated/rule_cards.md), [context_cards.md](../knowledge_base/generated/context_cards.md); [`src/rag/kb_builder.py`](../src/rag/kb_builder.py) | Örnek fraud politikası (block / review / allow ilkeleri, context, LLM'in rolü, değişiklik yönetimi; "gerçek kurum politikası değildir" notuyla), kural kartları, tipolojiler, analist prosedürü, feature sözlüğü; 60 chunk (K-53) | tam |
| 8 | Embedding | [`src/rag/embedder.py`](../src/rag/embedder.py) `OllamaEmbedder`; [`configs/rag.yaml`](../configs/rag.yaml) (`bge-m3`) | Yerel Ollama embedding (K-28) | tam |
| 8 | Vector search | [`src/rag/store.py`](../src/rag/store.py) `FaissVectorStore`; [`src/rag/retriever.py`](../src/rag/retriever.py) `HybridRetriever`; [`src/rag/chunker.py`](../src/rag/chunker.py) `chunk_markdown` | FAISS + kural kimliği filtresi, yapıya duyarlı chunking (K-30, K-31) | tam |
| 8 | LLM context injection | [`src/rag/prompt.py`](../src/rag/prompt.py) `PromptBuilder`; [`src/rag/llm.py`](../src/rag/llm.py) `OllamaLLMClient` | Chunk'lar ID'leriyle prompt'a girer, kaynak atfı zorunlu | tam |
| 8 | RAG tabanlı reasoning | [`src/rag/service.py`](../src/rag/service.py) `RAGService`; [step8.md](step8.md) "Gerçek çalıştırma"; [technical_doc.md §10](technical_doc.md#10-rag-adım-8) | Eşik altı cevapsız kalma, kaynak doğrulama, hit@k ölçümü | tam |

## Adım 9 - Multi-agent

| Adım | Case maddesi | Karşılayan dosya / fonksiyon / rapor | Kısa açıklama | Durum |
|---|---|---|---|---|
| 9 | Birden fazla agent | [`src/agents/`](../src/agents/): `CoordinatorAgent`, `FeatureAgent`, `AnomalyAgent`, `ContextAgent`, `RuleAgent`, `ExplainerAgent`; [`configs/agents.yaml`](../configs/agents.yaml); [step9.md](step9.md) | 6 agent. `FeatureAgent` ham işlemden kaydı `/score` ile aynı kodla üretir (`OnlineScorer.record_for` -> `FeaturePipeline.transform_one`), yalnızca agent akışında (K-54) | tam |
| 9 | Agent-to-agent communication | [`src/agents/bus.py`](../src/agents/bus.py) `MessageBus`; [`src/agents/messages.py`](../src/agents/messages.py) `BusMessage`, `TraceEntry`; [reports/agents/](../reports/agents/) trace'leri | Mediator; `correlation_id`, `parent_id` zinciri | tam |
| 9 | Task delegation | [`src/agents/coordinator.py`](../src/agents/coordinator.py) `CoordinatorAgent.analyze`; [`src/agents/planner.py`](../src/agents/planner.py) `Planner`; [step9.md "Delegation"](step9.md); [tests/agents/test_feature_agent.py](../tests/agents/test_feature_agent.py) | Koordinatör planı delege eder; eksik girdide agent'lar bus üzerinden birbirinden ister: rule -> context -> anomaly -> feature | tam |

## Adım 10 - API

| Adım | Case maddesi | Karşılayan dosya / fonksiyon / rapor | Kısa açıklama | Durum |
|---|---|---|---|---|
| 10 | `/score` | [`src/api/routers/score.py`](../src/api/routers/score.py) | Feature -> skor -> context -> kural; LLM çağırmaz | tam |
| 10 | `/explain` | [`src/api/routers/explain.py`](../src/api/routers/explain.py); [`src/api/services.py`](../src/api/services.py) | facts + agent trace + RAG narrative | tam |
| 10 | `/rules/evaluate` | [`src/api/routers/rules.py`](../src/api/routers/rules.py) | Yüklü veya istekte gelen kural setiyle değerlendirme | tam |
| 10 | `/rag/query` | [`src/api/routers/rag.py`](../src/api/routers/rag.py) | Bilgi tabanına soru, kaynaklarla | tam |
| 10 | FastAPI | [`src/api/main.py`](../src/api/main.py); [step10.md](step10.md); [technical_doc.md §12](technical_doc.md#12-api-adım-10); [examples/requests/](../examples/requests/) | Ek: `/health`, `/rules`, `/rules/reload` | tam |

## Bonus

| Adım | Case maddesi | Karşılayan dosya / fonksiyon / rapor | Kısa açıklama | Durum |
|---|---|---|---|---|
| Bonus | Tasarım desenleri | [technical_doc.md §3](technical_doc.md#3-tasarım-desenleri) | Strategy, Factory, Chain of Responsibility, Mediator, Repository, DI (her biri dosyasıyla) | tam |
| Bonus | dependency_injector container | [`src/container.py`](../src/container.py); routers'ta `@inject` + `Provide[Container.x]`; [tests/core/test_container_config.py](../tests/core/test_container_config.py) | Tüm servisler tek `DeclarativeContainer` içinde | tam |

## Teslim

| Adım | Case maddesi | Karşılayan dosya / fonksiyon / rapor | Kısa açıklama | Durum |
|---|---|---|---|---|
| Teslim | Source code | [`src/`](../src/), [`scripts/`](../scripts/), [`tests/`](../tests/), [`Makefile`](../Makefile) | `make pipeline`, `make test` | tam |
| Teslim | Teknik doküman | [technical_doc.md](technical_doc.md); adım dokümanları [step0.md](step0.md) ... [step10.md](step10.md); [decisions.md](decisions.md) | Türkçe | tam |
| Teslim | README ve çalıştırma adımları | [README.md](../README.md) "Kurulum", "Ollama ve modeller", "Veri yerleşimi", "Çalıştırma" | | tam |
