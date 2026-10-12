# Adım 8-10 bağımsız denetim (RAG, multi-agent, FastAPI + DI)

Tarih: 2026-10-12. Denetlenen commit: `2693a36` (main, temiz çalışma ağacı).
Kapsam: `src/rag/`, `src/agents/`, `src/api/`, `src/container.py`, `src/core/interfaces.py`, `configs/{rag,agents,api}.yaml`,
`knowledge_base/`, `scripts/{build_rag_index,run_agents_demo,run_pipeline}.py`, `tests/{rag,agents,api}/`, `docs/step8-10.md`, `README.md`.
Kaynak kod değiştirilmedi. Deneyler scratchpad'deki geçici scriptlerle yapıldı.

**Sonuç: DÜZELTME GEREKLİ** (0 KRİTİK, 6 ÖNEMLİ, 9 KÜÇÜK). Sızıntı, test, lint, DI ve katman yönü temiz; düzeltilmesi gerekenler
graceful degradation boşlukları, dokümanla kod arasındaki tutarsızlıklar ve bir testin gerçek veriye bağlı olması.

---

## 1. Kontrol listesi

| # | Kontrol | Durum | Kanıt |
|---|---|---|---|
| 1 | `make test` | ✅ | `408 passed, 1 skipped, 1 warning in 45.32s`. Skip: `tests/rag/test_retrieval_accuracy.py:24: needs Ollama; run with: pytest -m ollama` |
| 2 | `make lint` | ✅ | `ruff: All checks passed!`, `black: 199 files would be left unchanged.` |
| 3 | Leakage (`isFraud`) | ✅ | `grep -rn isFraud src/ scripts/ configs/ knowledge_base/` loader/evaluation dışında yalnızca yorum satırları ve `settings.yaml:14 label_column` var. `src/rag`, `src/agents`, `src/api`, KB içinde hiç geçmiyor. API şeması `isFraud` alanını reddediyor (deney: `REJECTED ... unknown field(s): ['isFraud']`). `run_agents_demo.py`, `consistency.py`, `examples.py`, `loadtest.py` kolonları açıkça seçerek okuyor (`api_columns` yalnızca `TransactionIn` alanları + `V\d+`) |
| 4 | Zamansal sızıntı (online) | ✅ | `online.py:151-165` `transform_one(update=False)` ile önce feature, sonra `_commit` (`online.py:221-223`) ile geçmişe ekleme yapıyor. `EMAIL_KNOWN` geçmiş store'dan geliyor. Sıra dışı işlem uyarı alıyor (`online.py:192-195`) |
| 5a | Case 8: KB, embedding, vector search, context injection, RAG reasoning | ✅ | 52 chunk (`chunks.jsonl` sayıldı: rule_card 14, context_card 14, operations 10, feature_dictionary 7, typology 7), bge-m3, FAISS IndexFlatIP, `PromptBuilder` + `RAGService`. Üretilen kartlar config ile güncel (yeniden üretilip karşılaştırıldı: `rule_cards same: True context_cards same: True`) |
| 5b | Case 9: birden fazla agent, agent-to-agent, delegation | ✅ | 5 agent + `MessageBus` (Mediator). Delegation zinciri `rule -> context -> anomaly` (`rule_agent.py:41-53`, `context_agent.py:34-39`) |
| 5c | Case 10: /score, /explain, /rules/evaluate, /rag/query | ✅ | `src/api/routers/{score,explain,rules,rag,health}.py`, hepsi `@inject` + `Provide[Container.x]` |
| 5d | Bonus: desenler + dependency_injector | ✅ | Mediator (bus), Factory (`AgentFactory`), Strategy/Chain (plan), Repository (`RuleRepository`), `DeclarativeContainer` |
| 6 | Doküman (step8/9/10) | ⚠️ | Üçünde de `isFraud kullanıldı mı: hayır` notu, çıktı şeması ve bilinen sınırlar var. Ancak Ollama kapalıyken davranış (Ö2), test verisi (Ö3) ve süre sınırı (Ö5) konularında yanlış iddialar var. `step10.md` içinde "Bir sonraki adımın girdisi" bölümü ve bellek notu yok (K8) |
| 7 | Sözleşme / container | ✅ | `HybridRetriever(Retriever)`, `OllamaLLMClient(LLMClient)`, `OllamaEmbedder(Embedder)`, `Agent(BaseAgent)`. `git diff 6f2138a HEAD -- src/container.py src/core/interfaces.py src/core/types.py` içinde silinen tek satır `Retriever.retrieve` imzası; yerine geriye uyumlu `filters=None` parametreli hali geldi (ekleme sayılır). Container'dan kayıt silinmemiş |
| 8 | DI kuralları | ✅ (küçük not) | Router'larda global yok. Testler `container.<x>.override(...)` kullanıyor (`tests/api/conftest.py:265-283`, `test_container_and_leakage.py:21-28`). Not: LLM/embedder kendi `httpx.Client`'ını kuruyor (K5). `main.py:82` modül seviyesinde `app = create_app()` uvicorn için standart; ihlal sayılmadı |
| 9 | Katman yönü | ✅ | Alt katmanlardan `src.api`/`src.agents` importu yok; `src.rag` yalnızca agents/api/container'dan import ediliyor (grep boş döndü). `src/rag` yalnızca `src.core` + kendi modüllerini import ediyor |
| 10 | Batch = online aynı kod | ✅ | `OnlineScorer.evaluate` (`online.py:169-206`) `score_one -> adjust_one -> engine.evaluate(unclipped)` sırasını izliyor; batch `run_rules.py` de unclipped skoru kullanıyor. Örneklem tutarlılık testi bu makinede koştu ve geçti (ama bkz. Ö3) |
| 11 | API istek anında eğitim yapmıyor | ✅ | `src/api`, `src/agents`, `src/rag`, `container.py` içinde `.fit(` yok. `/rules/reload` yalnızca dosya ve öğrenilmiş eşikleri yeniden okuyor (`rules/engine.py:100-105`). Açılış: 1,8 sn, RSS ~547 MB (ölçüldü) |
| 12 | Testler gerçek veriye bağlı değil | ❌ | `tests/api/test_batch_online_consistency.py` gerçek IEEE-CIS örneklemini okuyor (Ö3) |
| 13 | Ollama yokken graceful fallback | ⚠️ | `/score` etkilenmiyor (deney: `SCORE 200 block`, `HEALTH 200 degraded`). Planlayıcı varsayılan plana düşüyor. Ancak indeks yoksa `/explain` 503 dönüyor (Ö1) ve Ollama kapalıyken şablon açıklama üretilmiyor (Ö2) |
| 14 | Seed 42 | ✅ | `configs/rag.yaml: seed: 42`, `LLMConfig.seed=42` Ollama `options.seed` olarak gönderiliyor (`llm.py:54`), `indexer.py:39 set_seed`, FAISS flat (deterministik). Agent/API tarafında rastgelelik yok |
| 15 | Dosya alanları | ⚠️ | Agent tanımlarındaki alanların dışına yazılmış (Ö6) |
| 16 | Karar kayıtları | ✅ | `docs/decisions.md` K-28 ... K-43 mevcut; kişisel çalışma notları .gitignore'da |
| 17 | Örneklem -> tam veri | ⚠️ | Tam veri tutarlılık kontrolü (20/20) ve gecikme ölçümü dokümanda var. API örneklem artifact'larıyla çalışamıyor (Ö4) |

---

## 2. Bulgular

### KRİTİK
Yok.

### ÖNEMLİ

#### Ö1. RAG indeksi yokken `/explain` 503 dönüyor, `facts` de gelmiyor
- **Yer:** `src/container.py:118` (`explain_service` -> `api_coordinator` -> `api_agent_factory` -> `rag_service` -> `vector_store`), `src/rag/store.py:91-92` (`IndexNotBuiltError`), `src/api/errors.py:136-138` (503).
- **Sorun:** `ExplainService` oluşturulurken bağımlılık zinciri FAISS indeksini yüklüyor. İndeks yoksa servis hiç oluşturulamıyor ve istek `service.explain` çağrılmadan 503 ile bitiyor. K-40 ve `docs/step10.md` "facts koddan gelir, LLM'e bağlı değildir", README:63 de "Ollama yoksa narrative=null" diyor.
- **Kanıt (deney, gerçek artifact'lar, `rag_settings.paths.index_dir` boş klasör):**
  ```
  EXPLAIN 503 0.0 s
  {"error": {"code": "rag_unavailable", "message": "IndexNotBuiltError: RAG index not found in .../empty_index (run: make rag-index)", ...}}
  SCORE 200 block
  HEALTH 200 degraded
  ```
- **Somut etki:** İndeks Ollama olmadan kurulamıyor (`make rag-index` embedding ister) ve `artifacts/` gitignore'da. Repoyu klonlayıp Ollama kurmadan `make pipeline && make api` çalıştıran değerlendirici `/explain`'den hiç cevap alamaz; dokümandaki "facts her zaman döner" iddiası bozulur. Aynı nedenle `make agents-demo` de indeks yoksa `container.coordinator()` aşamasında çöker.
- **Seçenekler:**
  - A) **RAG'i agent içinde geç çözümle:** `AgentFactory`/`ExplainerAgent` `rag_service` yerine `rag_service.provider` (callable) alsın ve explain adımında çözsün. `IndexNotBuiltError` explainer hatası olur, bus bunu yakalar: facts + trace + `llm_status="unavailable"` döner. Artı: tüm trace korunur, agent demosu da indeks olmadan çalışır, `HealthService` zaten aynı deseni kullanıyor (`online_scorer.provider`). Eksi: agent'a nesne değil provider enjekte edilir, birkaç test güncellenir.
  - B) **`ExplainService` coordinator'ı try içinde çözsün:** `api_coordinator.provider` enjekte edilir, `services.py:48-52` içindeki try bloğunda çözülür. Artı: yalnızca API katmanında 3-4 satırlık değişiklik. Eksi: indeks yoksa agent trace'i tamamen boş kalır, demo script'i yine çöker.
  - C) **Null-object store:** indeks yoksa `load_vector_store` boş bir store döndürür, `RAGService` `index_missing` bayrağıyla cevap verir. Artı: `/rag/query` dahil her yol aynı şekilde 200 döner. Eksi: Adım 8'de dokümante edilen `IndexNotBuiltError` sözleşmesi değişir, yanlış yapılandırma gizlenebilir.
  - **Öneri:** A. Davranışı tek yerde (agent) düzeltir, hem API'yi hem demoyu kurtarır. Gerekçesi kısa: "geç bağlama".

#### Ö2. Ollama kapalıyken davranış dokümanda yanlış: şablon açıklama üretilmiyor, retrieval de yapılamıyor
- **Yer:** `docs/step9.md:79` ve `:130`, `docs/step8.md:69`, `README.md:29-30`, `scripts/run_agents_demo.py:9-10`. Kod: `src/rag/retriever.py:36` (embedding de Ollama'da), `src/agents/explainer_agent.py:99-104` (istisna yakalanmıyor).
- **Sorun:** Dokümanlar "Ollama kapalıysa RAG retrieval-only döner (`llm_unavailable`), agent şablon açıklamaya düşer" diyor. Oysa embedding modeli (bge-m3) de Ollama'da çalışıyor. Ollama kapalıyken retriever `EmbeddingUnavailableError` atar, explainer adımı hata verir, açıklama `null` olur, şablon üretilmez. Şablon yolu yalnızca "embedding çalışıyor, LLM yok" durumunda devreye giriyor ve testler de sadece bu durumu sahte RAG ile deniyor (`tests/agents/test_explainer.py:63-72`).
- **Kanıt (deney, Ollama host'u `127.0.0.1:9`):**
  ```
  agent explainer failed on explain: Ollama embedding endpoint unreachable (http://127.0.0.1:9): [Errno 61] Connection refused
  EXPLAIN 200 0.3 s
  facts.decision review llm_status unavailable narrative None
  agent {"status": "degraded", ... "errors": ["explainer:explain: explainer.explain failed: EmbeddingUnavailableError: ..."]}
  trace [... ('explainer', 'explain', 'error')]
  ```
- **Somut etki:** "Ollama yoksa şablon açıklama gelir" denip canlı gösterilirse açıklama `null` çıkar. README'deki "retrieval sonucu döner" iddiası `/rag/query` için de yanlış (`answer=null`, `sources=[]`).
- **Seçenekler:**
  - A) **Yalnızca dokümanı düzelt:** Gerçek davranış yazılır: Ollama tamamen kapalı -> explainer hatası, `explanation=null`, `status=degraded`. Sadece LLM modeli eksik -> retrieval-only + şablon. Artı: kod riski yok. Eksi: agent yolunda Ollama yokken analiste hiç açıklama metni gitmez.
  - B) **Kodu dokümana uydur:** `ExplainerAgent._explain`, `EmbeddingUnavailableError` / `LLMUnavailableError` alırsa şablon açıklama döndürsün (`origin="template"`, `flags=["llm_unavailable","explanation_fallback"]`, kaynak yok). Gerçek `RAGService` + hata atan embedder ile bir test eklenir. Artı: deterministik açıklama her zaman var, mevcut dokümanlar büyük ölçüde doğru hale gelir. Eksi: API'de bu metin `facts.summary` ile örtüşür (`to_narrative` şablonu zaten atıyor, yani API yanıtı değişmez, yalnızca agent/demo çıktısı değişir).
  - C) B + `README.md:29-30` ve `step8.md:69` içindeki "retrieval sonucu" ifadesini "embedding de Ollama'da olduğu için retrieval yapılamaz" diye düzeltmek.
  - **Öneri:** C. Kod değişikliği küçük; doküman ile kod aynı şeyi söyler ve gerçek hata senaryosu testle kapsanır.

#### Ö3. `make test` içinde gerçek veriye bağlı bir test var; dokümanda "sentetik" deniyor
- **Yer:** `tests/api/test_batch_online_consistency.py:22-29, 46-53`; `docs/step10.md:93` ("Aynı kontrol ... sentetik veriyle koşar").
- **Sorun:** Test `data/processed/merged_sample.parquet`, `features_sample.parquet` (gerçek IEEE-CIS örneklemi), `artifacts/*_sample` ve `reports/*/sample` dosyalarını okuyor. Dosyalar yoksa atlanıyor; bu makinede atlanmadı ve koştu (tek skip ollama testi). CLAUDE.md: "Testler hiçbir zaman gerçek veriye bağlı değildir."
- **Somut etki:** Proje kuralı ihlal ediliyor ve dokümanda yanlış bilgi var. Temiz klonda (CI) test sessizce atlanıyor, yani API seviyesinde batch=online kontrolünü varsayılan suite kapsamıyor. Test süresi de veri boyutuna bağlı hale geliyor.
- **Seçenekler:**
  - A) **Opt-in marker + sentetik API testi:** Test `@pytest.mark.data` ile işaretlenir ve `ollama` gibi varsayılanda koşmaz (`pyproject.toml` marker + `addopts = -m "not ollama and not data"` veya mevcut skip mantığı). Ayrıca küçük sentetik bir frame ile `FeaturePipeline` fit -> batch vs `/score` karşılaştıran bir test eklenir. Artı: kural tam karşılanır, CI'da da kapsama olur. Eksi: sentetik uçtan uca test yazmak emek ister.
  - B) **Yalnızca opt-in marker + doküman düzeltmesi:** Artı: hızlı. Batch=online alt katmanlarda zaten sentetik olarak test ediliyor (`tests/features/test_batch_online_equality.py`, `tests/scoring/test_service.py`, `tests/context/test_engine.py`). Eksi: API birleştirme kodu (`OnlineScorer.build_record`) için varsayılan suite'te batch=online kontrolü kalmaz.
  - C) **Testi tut, dokümanı düzelt:** Artı: sıfır kod. Eksi: CLAUDE.md kuralı ihlal edilmeye devam eder.
  - **Öneri:** B (asgari), zaman varsa A. Alt katmanlar sentetik olarak kapsandığı için B savunulabilir.

#### Ö4. API örneklem (`SAMPLE_N`) artifact'larıyla çalışamıyor
- **Yer:** `src/container.py:38-45, 48, 51` (sabit `feature_pipeline.joblib`, `entity_profiles.parquet`, `detectors/`); README:17, 37, 48 örneklemi "hızlı deneme" olarak öneriyor.
- **Sorun:** `SAMPLE_N=50000 make pipeline` `*_sample` / `detectors/sample/` yazıyor (`build_features.py:48`, `run_rules.py:258-259`), ama container yalnızca tam veri yollarını yüklüyor. Örneklemle pipeline koşup `make api` diyen kullanıcıda `/health` `down` olur, `/score` 503 döner. `src/api/consistency.py:52-67` örneklem modunu destekliyor, container desteklemiyor.
- **Somut etki:** CLAUDE.md'deki "önce örneklemle çalıştır" ilkesi API için geçerli değil. Kısıtlı RAM'li değerlendirici API'yi deneyemez. Bu durum README'de veya `step10.md`'de yazmıyor.
- **Seçenekler:**
  - A) **Container `SAMPLE_N`'e uysun:** `get_sample_n()` ile yollar seçilsin (feature pipeline, detectors/sample, context params, `reports/rules/sample` eşikleri; `consistency.build_scorer` ile aynı mantık). Artı: proje genelindeki SAMPLE_N kararıyla tutarlı. Eksi: container'a ortam değişkeni mantığı girer; kural eşikleri için ayrı kaynak bağlanmalı.
  - B) **Sadece dokümante et:** README ve step10'a "API tam veri artifact'ları ister; örneklemle `/health` down döner" notu eklenir. Artı: kod yok. Eksi: hızlı deneme yolu kapalı kalır.
  - C) **`configs/api.yaml: artifact_set: full|sample`:** Artı: ortam değişkeni sihri yok, açık bir ayar. Eksi: A ile aynı bağlama işi, bir ayar daha.
  - **Öneri:** A. Proje kararı zaten SAMPLE_N üzerine kurulu ve `consistency.py` mantığı yeniden kullanılabilir. Kullanıcı kararı gerekir.

#### Ö5. `/explain` süre sınırı 60 sn değil: soru verilince en kötü durumda yaklaşık 2 x 60 sn
- **Yer:** `src/api/config.py:58-68` (planlayıcı ve explainer ayrı ayrı 60 sn ile sınırlanıyor), `src/agents/planner.py:89` ve `src/agents/explainer_agent.py:99-104` (art arda çalışıyorlar); `docs/step10.md` ("LLM süre sınırı (60 sn)", "süre 60 sn'yi aşarsa facts ile `llm_status="timeout"` döner"), `configs/api.yaml:3`.
- **Kanıt (deney, sahte yavaş planlayıcı LLM + yavaş RAG, API sınırı 1 sn):**
  ```
  plan_fallback: no answer within 1s
  agent explainer failed on explain: no answer within 1s
  deadline=1s total=2.05s llm_status=timeout plan=fallback
  ```
- **Somut etki:** Soru içeren `/explain` istekleri 120 sn'ye kadar sürebilir. 60-90 sn timeout'lu istemciler bağlantıyı keser. Ayrıca terk edilen iki daemon thread Ollama'yı meşgul tutar ve sonraki istekleri yavaşlatır.
- **Seçenekler:**
  - A) **İstek başına tek bütçe:** `ExplainService` bir bitiş zamanı hesaplar, `AnalystRequest` içinde taşınır, planlayıcı ve explainer kalan süreyi kullanır. Artı: gerçek SLA. Eksi: Adım 9 mesaj sözleşmesine alan eklenir, agent'lar biraz karmaşıklaşır.
  - B) **Statik bölme:** `configs/api.yaml` içinde `planner_timeout_seconds` (örn. 10) + `explain_timeout_seconds` (örn. 50), toplamı `llm.timeout_seconds`'ı aşmayacak şekilde doğrulanır. `agent_settings_for_api` bunları uygular. Artı: config ve 5-10 satır kod; anlatması kolay. Eksi: planlayıcı hızlı bitince artan süre explainer'a aktarılmaz.
  - C) **Sadece dokümanı düzelt:** "soru yoksa ≤60 sn, soru varsa ≤120 sn". Artı: kod yok. Eksi: SLA gevşek kalır.
  - **Öneri:** B. Planlayıcı ölçümde 3,5-4,6 sn sürüyor; 10 sn'lik sabit pay yeterli ve gerekçesi basit.

#### Ö6. Geliştirme agent'larının dosya alanı dışına yazılmış
- **Yer (commit bazında, `git show --name-only`):**
  - rag-engineer (alan: `src/rag/, knowledge_base/, scripts/build_index.py, tests/rag/, data/vector_store/, docs/step8.md`): `configs/rag.yaml`, `scripts/build_rag_index.py` (alandaki ad `build_index.py`), `artifacts/rag/` (alanda `data/vector_store/`), `Makefile`, `README.md`, `pyproject.toml` (1f17406).
  - agent-orchestrator: `Makefile` (e224b6a).
  - api-engineer (alan: `src/api/, src/container.py, tests/api/, docs/step10.md, README.md`): `Makefile`, `scripts/run_pipeline.py`, `configs/api.yaml`, `examples/requests/*` (96a11f8).
  - `docs/decisions.md` kullanıcı kararıyla yazılıyor; ihlal sayılmadı.
- **Somut etki:** İşlevsel bir sorun yok. Kod, CLAUDE.md'deki "fit edilmiş nesneler `artifacts/` altında" kuralına agent tanımından daha uygun. Ancak "her agent yalnızca kendi alanına yazar" kuralı ve agent tanımları gerçekle uyuşmuyor; ileride başka bir reviewer veya agent yanlış dosyaları arar.
- **Seçenekler:**
  - A) **Agent tanımlarını gerçeğe göre güncelle** (`.claude/agents/rag-engineer.md`: `scripts/build_rag_index.py`, `configs/rag.yaml`, `artifacts/rag/`; `api-engineer.md`: `configs/api.yaml`, `examples/`, `Makefile`, `scripts/run_pipeline.py`). Artı: tek doğruluk kaynağı. Eksi: `.claude/` yapılandırması değişir, bunu yalnızca kullanıcı yapabilir/onaylayabilir.
  - B) **`docs/decisions.md`'ye istisna kaydı:** "Makefile/pipeline/config değişiklikleri K-43 ile kabul edildi". Artı: yapılandırmaya dokunulmaz. Eksi: tanımlar hâlâ yanlış kalır.
  - C) Dosyaları alanlara geri taşımak. Eksi: `artifacts/` kuralıyla çelişir, pratik değil.
  - **Öneri:** A, kullanıcı tarafından. Yapılamazsa B.

### KÜÇÜK (ana oturum uygulayacak; her biri için tek önerilen düzeltme)

| # | Yer | Sorun | Önerilen düzeltme |
|---|---|---|---|
| K1 | `scripts/build_rag_index.py:60` | Script `RAGService`'i `abstain_threshold`, `abstain_answer`, `ungrounded_warning` vermeden kuruyor. Örnek sorgu K-33 güvenilirlik katmanları olmadan çalışıyor (abstain eşiği 0, uyarı metni `"ungrounded answer"`) | İndeks kaydedildikten sonra servis container'dan alınsın: `from src.container import create_container` ve `service = create_container().rag_service()` (vector_store singleton'ı yeni indeksi o anda yükler). `--no-llm` dalı da `container.retriever()` kullanabilir |
| K2 | `scripts/run_agents_demo.py:3, 9-10` | Docstring `[--no-llm]` diyor ama argparse'ta yok: `run_agents_demo.py: error: unrecognized arguments: --no-llm` | Docstring'den `[--no-llm]` kaldırılsın ve 9-10. satırlar Ö2 sonucuna göre gerçek davranışla güncellensin |
| K3 | `src/api/mappers.py:119-128`, `src/api/schemas.py` (`LlmStatus`) | Geçerli bir LLM planı explainer'ı atlayınca (örn. "sadece karar") `llm_status="error"` dönüyor. Deney: `plan ['rule:evaluate'] llm status ok llm_status error narrative None` | `LlmStatus`'a `"skipped"` eklensin; `classify_llm` başında `explanation is None` ve `"explainer:explain" not in response.plan.steps` ise `"skipped"` dönsün; test eklensin ve step10'daki `llm_status` listesine yazılsın |
| K4 | `src/api/schemas.py:161, 302` ve `configs/api.yaml:11` | `max_length=1000` şemada sabit yazılmış. `rag.max_question_chars` config'te tanımlı ama hiçbir yerde kullanılmıyor (grep: yalnızca `config.py`'de). "Sihirli sayı yok" kuralına aykırı | Ölü ayar kaldırılsın: `configs/api.yaml` ve `RagApiSettings` içinden `max_question_chars` silinsin, şemadaki `1000` tek bir modül sabiti (`MAX_QUESTION_CHARS`) olarak `schemas.py` başında yorumla tanımlansın (pydantic şeması config'i import zamanında okuyamaz) |
| K5 | `src/rag/llm.py:26`, `src/rag/embedder.py:22` | Sınıflar `client or httpx.Client(...)` ile kendi bağımlılıklarını kuruyor (DI kuralı: servis içinde `new` yok) | Container'a `llm_http_client = providers.Singleton(httpx.Client, base_url=rag_settings.provided.llm.host, timeout=rag_settings.provided.llm.timeout_seconds)` ve embedding için eşdeğeri eklensin, constructor'a verilsin; `client` parametresi zorunlu olsun |
| K6 | `docs/step8.md:19` ve `:59` (K-32 bölümü) | "Çalışma zamanında (API, Adım 9)" yazıyor, API Adım 10. Ayrıca K-32 bölümü abstain cümlesini "Bilgi tabanında bu bilgi yok." diye veriyor; config ve kod `"Bilgi tabanında bu konuda bilgi yok"` kullanıyor | "(API, Adım 10)" yapılsın; K-32 alıntısı config'teki cümleyle aynı hale getirilsin |
| K7 | `docs/step9.md:141` | "serbest metin soru olduğu gibi RAG sorgusu olur; sorgu yeniden yazımı yoktur" ifadesi K-39 (görev cümleleri çıkarılır, skor kaynaklı sorgu kurulur) ile çelişiyor | Şöyle değiştirilsin: "Soru, görev cümleleri regex ile çıkarıldıktan sonra RAG sorgusu olur; LLM tabanlı sorgu yeniden yazımı yoktur" |
| K8 | `docs/step10.md` | "Bir sonraki adımın girdisi" bölümü yok (docs-delivery kuralı). Tam veri bellek notu yok | Teknik doküman (docs-writer) için girdi bölümü eklensin: endpoint tablosu, örnek istekler, K-40...K-43, gecikme tablosu. Bellek notu: "tam veri artifact'larıyla açılış 1,8 sn, süreç RSS ~547 MB (`create_container().online_scorer()`, 2026-10-12 ölçümü)" |
| K9 | `docs/step10.md` Bilinen sınırlar | `/rules/reload` kural motorunu günceller ama KB kural kartlarını ve FAISS indeksini güncellemez; RAG eski kartı alıntılayabilir. `reload` ayrıca `OnlineScorer` kilidi dışında çalışıyor | Bilinen sınırlara madde eklensin: "/rules/reload sonrası açıklamaların güncel kartı kullanması için `make rag-index` gerekir; reload, eşzamanlı /score ile kilitlenmez (tek kullanıcılı yönetim işlemi varsayılır)" |

---

## 3. Doğrulanan olumlu noktalar (kısa)
- `/score` hiçbir LLM nesnesine bağlı değil (`OnlineScorer` bağımlılıkları: pipeline, scoring, adjuster, engine, settings). Ollama kapalıyken 200 dönüyor (deneyle doğrulandı).
- Karar yalnızca `RuleAgent`'tan kopyalanıyor (`coordinator.py:165-176`); `ExplainReply` içinde karar alanı yok; LLM planı `rule:evaluate` adımı olmadan reddediliyor (`planner.py:114-115`).
- Bus hiçbir agent hatasını dışarı atmıyor; delegation derinliği sınırlı (`bus.py:47-56`).
- `/score` TransactionID başına idempotent; `analyze` salt okunur; cooldown yalnızca `/score`'da yazılıyor (K-35).
- Abstain skoru metadata ile öne alınan kartlardan bağımsız (`retriever.py:37-40`).
- Üretilen KB kartları config ile birebir güncel; indeks `artifacts/rag/` altında ve gitignore'da.
- Test sayıları dokümanla uyumlu: rag 51 (50 + 1 ollama), agents 48, api 50.

## 4. Kullanıcının karar vermesi gerekenler
1. Ö1: RAG'in geç çözümlenmesi (A) mı, ExplainService içinde yakalama (B) mı?
2. Ö2: Ollama kapalıyken şablon açıklama kodla mı sağlansın (B/C), yoksa yalnızca doküman mı düzeltilsin (A)?
3. Ö3: Gerçek veri testi opt-in marker'a mı alınsın (B), sentetik API testi de eklensin mi (A)?
4. Ö4: API `SAMPLE_N`'i desteklesin mi (A/C), yoksa yalnızca dokümante mi edilsin (B)?
5. Ö5: `/explain` süre bütçesi statik bölünsün mü (B), tek dinamik bütçe mi olsun (A)?
6. Ö6: `.claude/agents/*.md` dosya alanları güncellensin mi (yalnızca kullanıcı)?
