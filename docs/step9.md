# Adım 9 - Çoklu agent orkestrasyonu (`src/agents/`)

**isFraud kullanıldı mı: hayır.** Agent katmanı (`src/agents/`, `configs/agents.yaml`, `scripts/run_agents_demo.py`) etiketi hiçbir yerde okumaz (`tests/agents/test_container.py` dosyaları tarar). Demo işlemleri yalnızca kural motorunun batch kararına göre seçildi (`reports/rules/rule_hits.parquet` içindeki `final_decision`).

Karar kayıtları: K-34 ... K-39 (`docs/decisions.md`). Bu doküman yalnızca ürünün içindeki runtime agent'ları anlatır.

## Ne yapıldı
Adım 4-8 servislerinin (anomali skoru, context düzeltme, kural motoru, RAG) tek bir isteği birlikte işlemesini sağlayan beş agent ve bir mesaj bus'ı yazıldı. Sonradan (K-54) ham işlemden feature'lı kaydı üreten altıncı bir agent, `FeatureAgent`, eklendi. Skor ve karar deterministik servislerden gelir; yerel LLM yalnızca (1) serbest metinli soruda hangi agent'ların çalışacağını planlamak ve (2) analist açıklamasını yazmak (RAG) için kullanılır.

## Agent rolleri
| Agent | Sorumluluk | Kullandığı servis (container) | Intent |
|---|---|---|---|
| `CoordinatorAgent` | İsteği alır, planı çıkarır, adımları bus ile delege eder, sonuçları birleştirir | `Planner` | `analyze` |
| `AnomalyAgent` | Katman skorları ve normalize toplam skor (Adım 4-5) | `scoring_service` | `score` |
| `ContextAgent` | Context düzeltmesi ve uygulanan C kuralları (Adım 6) | `context_adjuster` | `adjust` |
| `RuleAgent` | Kural değerlendirmesi, **tek karar kaynağı**, tetiklenen/bastırılan kurallar (Adım 7) | `rule_engine` | `evaluate` |
| `ExplainerAgent` | RAG ile analist açıklaması, "destek bilgisi" etiketli (Adım 8) | `rag_service` | `explain` |
| `FeatureAgent` (K-54) | Ham işlemden skorlanacak kaydı üretir (Adım 3 `FeaturePipeline.transform_one` + ham alanlar); yeni feature mantığı yoktur, `/score` ile aynı kodu salt okur çalıştırır. Plan adımı değildir, yalnızca AnomalyAgent'ın delegation'ıyla çağrılır | `online_scorer` (`RecordSource` arayüzü, sağlayıcı olarak) | `featurize` |

Roller, izinli intent'ler, varsayılan plan, zaman aşımları ve planlayıcı prompt'u `configs/agents.yaml` içindedir. `feature` bir plan rolü olmadığı için oradaki `roles` listesinde yoktur; planlayıcı onu seçemez.

## Mesaj formatı
`BusMessage` (pydantic v2), ortak `AgentMessage` türünü genişletir (`src/agents/messages.py`):

| Alan | Anlam |
|---|---|
| `message_id` | Mesaj başına benzersiz kimlik |
| `correlation_id` | Bir analist isteğindeki tüm mesajlar için aynı |
| `parent_id` | Gönderen hangi mesajı işlerken bunu yolladı (delegation zinciri) |
| `sender`, `recipient` | Agent adları (`client` dış çağıran) |
| `intent` | `analyze`, `score`, `adjust`, `evaluate`, `explain` |
| `payload` | Intent'e özgü, alıcı tarafından pydantic ile doğrulanan sözlük (`ScoreRequest`, `AdjustRequest`, `EvaluateRequest`, `ExplainRequest` ve cevap karşılıkları; fazladan alan reddedilir) |
| `timestamp`, `status` | UTC zaman, `ok` / `error` / `skipped` |

Trace (`TraceEntry`): `seq, message_id, parent_id, sender, recipient, intent, status, duration_ms, timestamp, payload_keys, detail`. Kayıt büyük olduğu için trace payload'ın yalnızca anahtarlarını tutar. `duration_ms` iç içe delegation'ı da kapsar. Bus dışı olaylar (`plan_fallback`) aynı listeye `recipient="-"` ile yazılır.

## Akış
```mermaid
sequenceDiagram
    participant C as client
    participant K as coordinator
    participant B as MessageBus
    participant A as anomaly
    participant F as feature
    participant X as context
    participant R as rule
    participant E as explainer
    C->>B: analyze(record veya transaction, question?)
    B->>K: analyze
    K->>K: plan (varsayılan veya LLM, doğrulanır)
    K->>B: score
    B->>A: score
    opt ham işlem geldiyse (kayıt yok)
        A->>B: featurize (delegation)
        B->>F: featurize
        F-->>A: kayıt (feature'lar + ham alanlar)
    end
    A-->>K: anomaly_score, layer_scores (+ üretilen kayıt)
    K->>B: adjust (skorlarla)
    B->>X: adjust
    X-->>K: adjusted_score, C kuralları
    K->>B: evaluate (skorlarla)
    B->>R: evaluate
    R-->>K: karar, tetiklenen/bastırılan kurallar
    K->>B: explain (kural sonucuyla)
    B->>E: explain
    E-->>K: destek bilgisi (karara etkisiz)
    K-->>C: AgentResponse + trace
```
Varsayılan plan: `anomaly:score -> context:adjust -> rule:evaluate -> explainer:explain`. Açıklama sorusu verilirse `question` hem planlayıcıya hem RAG sorgusuna gider.

Girdi iki biçimde gelebilir (`AnalystRequest`, ikisinden tam olarak biri): `record` = hazır feature'lı kayıt (demo'nun holdout işlemleri) veya `transaction` = ham işlem (`/explain`, demo'nun ham işlem örneği). Ham işlemde AnomalyAgent kaydı FeatureAgent'tan ister; üretilen kayıt `ScoreReply.record` / `AdjustReply.record` ile geri döner ve koordinatör sonraki adımlara ham işlem yerine bu kaydı verir. Kayıt bir kez üretilir.

### Delegation
Koordinatör her adıma o ana kadarki sonuçları verir. Bir adımda girdi eksikse agent onu bus üzerinden ister:
`RuleAgent` skor almamışsa `ContextAgent`'a `adjust` yollar; `ContextAgent` skor almamışsa `AnomalyAgent`'a `score` yollar; `AnomalyAgent` kayıt yerine ham işlem aldıysa `FeatureAgent`'a `featurize` yollar. Böylece LLM planı `anomaly` ve `context` adımlarını atlasa bile zincir kurulur (aşağıdaki ikinci örnek). Agent'lar birbirini import etmez (`test_agents_do_not_import_each_other`).

### Planlama (K-37)
- Soru yoksa: varsayılan plan, LLM çağrılmaz.
- Soru varsa: yerel LLM'den `{"steps":[{"agent","intent"}]}` istenir. Pydantic doğrulaması: ek alan yok, yalnızca config'teki agent:intent çiftleri, tekrar yok, bağımlılık sırasında, `rule:evaluate` zorunlu, soru varsa `explainer:explain` de zorunlu (K-51; `workflow.question_required_step`). LLM kapalı, zaman aşımı (batch/demo 60 sn, API 10 sn), geçersiz JSON, izinsiz agent, sıra hatası, eksik kural adımı veya eksik açıklama adımı: varsayılan plana düşülür ve trace'e `plan_fallback` + sebep yazılır.
- Plan karar kaynağını değiştiremez: kural adımı zorunlu, karar yalnızca `EvaluateReply`'dan kopyalanır, `ExplainReply` tipinde karar alanı yoktur. Testler: LLM'in "decision: allow" eklemesi reddedilir, açıklama metni "allow" dese de karar `block` kalır, kural adımsız plan reddedilir.

## Dayanıklılık (K-38)
| Durum | Sonuç |
|---|---|
| RAG cevabı boş / yalnızca kaynak satırı / LLM yok | Şablon açıklama, `origin=template`, trace'te `explanation_fallback` |
| ExplainerAgent hatası / zaman aşımı (240 sn) | Karar aynen döner, `explanation=null`, `status=degraded`, trace'te `explainer` `status=error` |
| Embedding çalışıyor, LLM kapalı | RAG retrieval-only döner (`llm_unavailable`, `text=null`); agent bunu boş sayıp şablon açıklamaya düşer, kaynaklar korunur |
| Ollama tamamen kapalı (embedding de yok) veya indeks kurulmamış | Retrieval yapılamaz (`EmbeddingUnavailableError` / `IndexNotBuiltError`); agent şablon açıklama döner, `flags=["rag_unavailable","explanation_fallback"]`, kaynak yok. RAG servisi agent'a sağlayıcı (provider) olarak verildiği için indeks yalnızca bu adımda yüklenir; skor, context, kural adımları ve trace etkilenmez (Adım 8-10 review, Ö1/Ö2) |
| Planlayıcı LLM hatası | Varsayılan plan, `plan_fallback` |
| Anomaly/Context hatası | Hata kaydedilir; RuleAgent skoru kendisi ister, o da başarısızsa `decision=null`, `status=error` |
| RuleAgent hatası | `decision=null`, `status=error`; karar uydurulmaz |
Bus hiçbir agent hatasını istisna olarak dışarı atmaz; delegation derinliği 6 ile sınırlıdır.

## Cooldown durumu (K-35, kullanıcı onayladı)
RuleAgent kural motorunu `update_state=False` ile çağırır: agent yolu K-27 online cooldown deposunu yazmaz, demo ve testler depoyu kirletmez. Karar: Adım 10'da yalnızca `/score` endpoint'i depoyu günceller; agent yolu ve diğer endpoint'ler salt okurdur. Bedeli: agent yolundan analiz edilen işlemler depoyu ilerletmez.

## Açıklama sorgusu ve şablona düşme (K-39)
- Sorgu kararın gerçek nedeninden kurulur. Analist sorusundaki görev cümleleri ("incele", "inceleme notu yaz", "sadece karar") çıkarılır. Geriye soru kalmaz ve karar kural tetiklenmeden skor eşiğinden gelmişse sorgu skor eşiğini, en yüksek iki katmanı ve operasyon rehberindeki review adımlarını hedefler; kural kararında varsayılan kural sorusu kullanılır.
- RAG cevabı boşsa, `null` ise (LLM yok) ya da yalnızca kaynak satırıysa şablon açıklama kullanılır: karar nedeni (`reasons`), en yüksek katman skorları, uygulanan C kuralları. Trace'e `explanation_fallback` yazılır; çıktı `origin="template"` ve yine "destek bilgisi" etiketlidir, karara etkisi yoktur.

## Gerçek demo (`make agents-demo`)
Holdout'tan kural motorunun batch kararına göre üç işlem seçilir (her karar grubunun ortadaki TransactionID'si; cooldown tarafından elenmiş satırlar atlanır, çünkü online depo boştur) ve hazır kayıtla gönderilir. Dördüncü çalıştırma (K-54) ham bir işlemdir: `examples/requests/review.json` (TransactionID 91000001); kaydı FeatureAgent üretir. Gerçek Ollama (qwen2.5:7b, bge-m3) ile çalıştırıldı (2026-10-12, K-54 sonrası yeniden üretim); dördünde de online karar beklenen batch kararıyla aynı çıktı. Dosyalar: `reports/agents/trace_{block,review,allow}_<id>.json`, `trace_raw_review_91000001.json`, `summary.json`.

| TransactionID | Girdi | Soru / plan | Karar | Tetiklenen | Context | Süre |
|---|---|---|---|---|---|---|
| 3522622 | kayıt | yok / varsayılan (4 adım) | block (R01) | R01 | C3, C6b | 77,5 sn (açıklama 77,4 sn) |
| 3519086 | kayıt | "incele ve inceleme notu yaz" / LLM: rule, explainer | review (skor eşiği) | - | C6a | 107,0 sn (plan 10,6 sn, açıklama 96,2 sn) |
| 3517771 | kayıt | "sadece karar" / LLM planı reddedildi -> varsayılan | allow | - | C1, C5, C9b | 75,0 sn (plan 8,5 sn, açıklama 66,4 sn) |
| 91000001 | ham işlem | yok / varsayılan | review (R04) | R04 | C3, C8, C9b | 80,1 sn (featurize 0,9 sn, açıklama 79,1 sn) |

3517771'de LLM yalnızca `rule:evaluate` planladı; K-51 gereği soru varsa açıklama adımı zorunlu olduğu için plan reddedildi ve trace'e `plan_fallback` ("plan has no explanation step although the analyst asked a question") yazıldı. Önceki koşudaki (K-51 öncesi) 3,7 sn'lik "yalnızca karar" sonucu artık geçerli değil. Süreler önceki koşudan uzundur (açıklama 66-96 sn): `num_predict` sınırı ve modelin o anki yükü etkiler; ölçüm tek koşudur.

Örnek trace (TransactionID 3519086, LLM planı `rule:evaluate -> explainer:explain`; `rule` eksik skoru zincirle aldı):
```
1. client      -> coordinator  analyze   [ok] 106961 ms
2. coordinator -> rule         evaluate  [ok]    178 ms
3. rule        -> context      adjust    [ok]    159 ms   (delegation, parent = 2)
4. context     -> anomaly      score     [ok]    144 ms   (delegation, parent = 3)
5. coordinator -> explainer    explain   [ok]  96163 ms
```

Ham işlem trace'i (TransactionID 91000001, K-54; AnomalyAgent kaydı FeatureAgent'tan istedi):
```
1. client      -> coordinator  analyze   [ok]  80103 ms
2. coordinator -> anomaly      score     [ok]    931 ms
3. anomaly     -> feature      featurize [ok]    857 ms   (delegation, parent = 2)
4. coordinator -> context      adjust    [ok]     10 ms
5. coordinator -> rule         evaluate  [ok]     14 ms
6. coordinator -> explainer    explain   [ok]  79146 ms
```
`featurize` süresinin çoğu feature pipeline ve entity store'un ilk yüklenmesidir (sağlayıcı ilk kullanımda çözülür).
Aynı işlemin yanıtından (kısaltılmış): `decision: "review"`, `decision_source: "score"`, `reasons: ["Karar kuralı tetiklenmedi; skor 1.079 inceleme eşiğinin (1.070) üzerinde."]`, `explanation: {label: "destek bilgisi", origin: "rag", affects_decision: false, grounded: true, ...}`. Görev cümlesi sorgudan çıkarıldığı ve karar skor eşiğinden geldiği için RAG `operations_guide#skor-kaynakli-review` ve `feature_dictionary#skor-alanlari` bölümlerini getirdi; metin skor eşiğini ve review adımlarını anlatıyor (önceki sürümde ilgisiz R07 kartı ve yalnızca kaynak satırı dönmüştü). Gerçek demoda şablona düşme gerekmedi; bu yol testlerle doğrulandı.

Block örneğinde (varsayılan plan) açıklama R01 kartından ve operasyon rehberinden alıntılı, `grounded=true`; yanıt kural gerekçesini (`0.88 USD küçük tutar ... son 1 saatte 15 önceki küçük işlem`) ayrıca `reasons` içinde taşır.

## Dosyalar
| Yol | İçerik |
|---|---|
| `src/agents/messages.py` | `BusMessage`, payload ve `AgentResponse`/`TraceEntry` modelleri |
| `src/agents/bus.py` | `MessageBus` (Mediator, trace, derinlik sınırı) |
| `src/agents/base.py` | `Agent` tabanı (`on(intent, handler)`, `delegate(...)`) |
| `src/agents/{anomaly,context,rule,explainer,feature}_agent.py`, `coordinator.py` | Agent'lar |
| `src/agents/planner.py` | Varsayılan plan, LLM planı ve doğrulama |
| `src/agents/factory.py` | `AgentFactory`, planlayıcı LLM'i, `create_coordinator` |
| `src/agents/config.py`, `timeouts.py`, `errors.py` | Config modeli, sert zaman aşımı, istisnalar |
| `configs/agents.yaml` | Roller, plan, süreler, prompt |
| `scripts/run_agents_demo.py`, `reports/agents/` | Demo ve trace çıktıları |
| `tests/agents/` | 57 test (LLM, RAG, servisler sahte); FeatureAgent delegation zinciri: `test_feature_agent.py` |

Container (yalnızca ekleme): `agents_settings`, `message_bus`, `planner_llm`, `planner`, `agent_factory`, `coordinator` (hepsi Singleton). K-54: `agent_factory` ve `api_agent_factory` FeatureAgent için `records=online_scorer.provider` alır; bu yüzden `api_settings` ve `online_scorer` tanımları Adım 9 bloğunun üstüne taşındı (kayıt silinmedi). Sağlayıcı olarak verildiği için feature pipeline ve entity store yalnızca FeatureAgent çalışınca yüklenir. Testlerde `container.rule_engine.override(...)`, `container.rag_service.override(...)` vb. kullanılır. Tasarım desenleri: Mediator (bus), Factory (`AgentFactory`), Strategy/Chain (plan adımları sırayla), Repository (kural yükleme Adım 7'de).

## Komutlar
`make agents-demo` (en iyi sonuç için Ollama ve `make rag-index` gerekir; Ollama veya indeks yoksa demo yine biter: plan varsayılana düşer, açıklama şablondan gelir). Testler: `make test` (Ollama gerekmez).

## Bilinen sınırlar
- **Gecikme:** açıklama adımı 16-96 sn (son koşu 66-96 sn) (RAG, yerel 7B model; ilk istekte model yükleme dahil), LLM planı 3,5-4,6 sn. Karar ise 0,1-0,2 sn'de hazırdır; asıl bekleyen açıklamadır. Bus eşzamanlıdır (K-36), bir istek bitene kadar bir worker meşgul olur.
- **"Grounded" sınırı:** Adım 8'deki kaynak kontrolü yalnızca anılan chunk id'lerinin getirilenler arasında olduğunu doğrular, içeriğin doğruluğunu değil. 3519086'nın yeni açıklaması `grounded=true` ama içerik hatası var: "entity" katmanını "cihaz geçmişine bakılır" diye anlatıyor ve eşiği "1,070'den büyük olmalı" diye yorumluyor (skor kaynaklı review'da ölçüt skorun eşiğe ulaşmasıdır). 7B model bağlamı yer yer yanlış özetliyor. Bu yüzden çıktı "destek bilgisi"dir; karar ve gerekçe `reasons` alanındadır.
- **Görev cümlesi tespiti regex tabanlıdır** (`explainer.task_patterns`); listede olmayan bir görev ifadesi sorguda kalabilir. Boş-cevap kontrolü yalnızca boş/kaynak-satırı durumunu yakalar, yanlış ama dolu cevabı yakalamaz; abstain ("bilgi yok") cevabı da şablona düşürülmez.
- **LLM planının değeri sınırlı:** plan yalnızca yardımcı agent'ların seçimini etkiler (örn. açıklama atlayıp ~30 sn kazanmak). Planın kalitesi ölçülmedi; küçük bir soru kümesiyle değerlendirilmedi.
- **Zaman aşımında arka plan thread'i:** süre dolunca istek döner, ama LLM/RAG çağrısı HTTP timeout'una kadar arka planda sürer (daemon thread).
- **Retry ve paralellik yok;** mesajlar süreç içidir, kalıcı kuyruk yoktur.
- **Ham işlem ve geçmiş durum (K-54):** FeatureAgent kaydı online entity store'dan üretir; bu depo verinin son satırından sonraki durumdur. Bu yüzden demo holdout işlemlerini hazır kayıt olarak (batch feature'larından) gönderir: eski bir işlemi online yeniden üretmek kendi sonraki işlemlerini geçmiş sayardı. Ham işlem yolu `/explain` ve demo'nun API örneğiyle (yeni TransactionID) gösterilir. `/score`'un daha önce işlediği bir işlem için FeatureAgent aynı kaydı döner (`OnlineScorer.record_for`).
- **Agent yolu cooldown depoya yazmaz** (K-35); Adım 10'da yalnızca `/score` yazar.
- **Açıklama sorgusu:** görev cümleleri regex ile çıkarıldıktan sonra kalan metin RAG sorgusu olur (K-39); LLM tabanlı yeniden yazım yoktur.

## Bir sonraki adımın girdisi (Adım 10: API)
- `Container.coordinator().analyze(AnalystRequest(record=..., question=...)) -> AgentResponse` tek giriş noktasıdır; yanıt `decision`, `reasons`, `explanation` (destek bilgisi) ve `trace` içerir.
- API ham işlemden feature'lı kaydı üretmeli (Adım 3 `FeaturePipeline`) ve zaman aşımlarını (açıklama 240 sn) HTTP seviyesinde ele almalı; sync endpoint veya iş kuyruğu seçimi gerekir.
- Cooldown deposu: yalnızca `/score` `update_state=True` ile günceller; agent yolu ve diğer endpoint'ler salt okur (K-35).
