# Adım 10 - FastAPI servisi (`src/api/`)

**isFraud kullanıldı mı: hayır.** `src/api/`, şemalar ve `examples/requests/` etiketi okumaz (`tests/api/test_container_and_leakage.py` bu dosyaları tarar). Örnek istekler holdout'tan, yalnızca `reports/rules/rule_hits.parquet` içindeki batch `final_decision` değerine göre seçildi (kural çıktısı, etiket değil).

Karar kayıtları: K-35 (cooldown yalnızca `/score`'da yazılır), K-40 ... K-43 (`docs/decisions.md`).

## Ne yapıldı
Adım 3-9 servisleri tek bir FastAPI uygulamasında toplandı. Endpoint'ler ince katmandır (`@inject` + `Provide[Container.x]`, global durum yok); iş mantığı `OnlineScorer`, `ExplainService`, `RagQueryService`, `HealthService` içindedir. API istek anında model eğitmez: dedektörler, feature pipeline, context parametreleri ve kural eşikleri `artifacts/` ve `configs/` altından açılışta yüklenir.

| Dosya | Görev |
|---|---|
| `src/api/main.py` | `create_app(container)`, request id, log, lifespan (ısınma) |
| `src/api/routers/` | `score.py`, `explain.py`, `rules.py`, `rag.py`, `health.py` |
| `src/api/schemas.py` | pydantic v2 istek/yanıt şemaları (OpenAPI örnekleri dahil) |
| `src/api/online.py` | ham işlem -> kayıt -> katman skorları -> context -> kurallar; çevrimiçi geçmiş |
| `src/api/services.py`, `mappers.py` | `/explain` ve `/rag/query` servisleri, yanıt eşlemeleri |
| `src/api/errors.py` | tutarlı JSON hata zarfı (422/503/500) |
| `src/api/config.py`, `configs/api.yaml` | LLM süre sınırı (60 sn), önbellek boyutları, `/rag/query` sınırları |
| `src/api/consistency.py`, `loadtest.py`, `examples.py` | batch = online kontrolü, gecikme testi, örnek istek üretimi |
| `src/container.py` | yalnızca ekleme: `api_settings`, `online_scorer`, `api_*` agent kopyası, `explain_service`, `rag_query_service`, `health_service` |

## Endpoint tablosu
| Endpoint | Metot | Amaç | LLM | Durum yazar mı |
|---|---|---|---|---|
| `/score` | POST | Ham işlem -> katman skorları, adjusted skor, context kuralları, final skor/karar, tetiklenen/bastırılan kurallar, gerekçeler | Hayır | Evet (entity geçmişi + R03 cooldown, TransactionID başına bir kez) |
| `/explain` | POST | Aynı girdi + opsiyonel soru. `facts` (kod) + `narrative` (LLM) + agent trace | Evet (opsiyonel) | Hayır |
| `/rules/evaluate` | POST | Kural motoru; opsiyonel `rules` alanı yalnızca o istekte kullanılır | Hayır | Hayır (cooldown'u okur) |
| `/rag/query` | POST | `question`, `k`, `filters.rule_ids` -> `answer`, `sources`, `abstained`, `grounded`, `llm_status` | Evet | Hayır |
| `/health` | GET | Model artifact'ları, FAISS indeksi, Ollama (her zaman 200) | Hayır | Hayır |
| `/rules` | GET | Yüklü kurallar | Hayır | Hayır |
| `/rules/reload` | POST | Kural dosyalarını yeniden yükler; geçersizse 422 ve eski set geçerli kalır | Hayır | Hayır |

Zorunlu girdi alanları: `TransactionID, TransactionDT, TransactionAmt, ProductCD, card1`; eksikse 422. Diğer ham alanlar (card2-6, addr1-2, dist, P/R_emaildomain, C1-14, D1-15, M1-9, `id_*`, DeviceType/Info, V1-V339) opsiyoneldir; bilinmeyen alan reddedilir.

## Örnek istek / yanıt
Gövdeler `examples/requests/` altındadır (`block.json`, `review.json`, `allow.json`, `explain_review.json`, `explain_question.json`, `rules_invalid.json`, `rag_query.json`). `python -m src.api.examples` yeniden üretir; her örnek, API'de de batch kararıyla aynı kararı verdiği doğrulanarak seçilir.

```bash
curl -s -X POST localhost:8000/score -H 'Content-Type: application/json' -d @examples/requests/block.json
```
Yanıt (gerçek çıktı, tam veri artifact'ları; `reason` metinleri kısaltıldı):
```json
{"transaction_id": 91000000, "anomaly_score": 0.9515, "raw_anomaly_score": 0.8245,
 "layer_scores": {"multivariate": 0.9070, "entity": 0.4342, "column": 0.9926, "temporal": 1.0},
 "adjusted_score": 0.9943,
 "context_rules": [{"id": "C3", "name": "weekend_established_entity", "factor": 0.95, "reason": "..."},
                   {"id": "C6b", "name": "missing_country_converted_amount", "factor": 1.1, "reason": "..."}],
 "final_score": 1.0, "final_decision": "block", "decision_source": "R01",
 "triggered_rules": [{"id": "R01", "priority": 1, "severity": "critical", "decision": "block", "risk_boost": 0.3},
                     {"id": "R03", "priority": 2, "severity": "high", "decision": "review", "risk_boost": 0.15}],
 "suppressed_rules": [{"id": "R03", "reason": "R01 kazandı (öncelik 1, critical, block): daha yüksek öncelik (1 < 2)", "message": "..."}],
 "reasons": ["Kart testi şüphesi: 23.06 USD küçük tutar (eşik 25.95 USD) ve aynı entity'de son 1 saatte 20 önceki küçük işlem."],
 "warnings": ["out_of_order_transaction"],
 "duplicate": false, "state_updated": true, "latency_ms": 193.0}
```
Aynı `TransactionID` ikinci kez gönderilince aynı skorlar `duplicate=true`, `state_updated=false` ile döner (0 ms) ve durum bir daha yazılmaz.

Üç örnek canlı API'de (tam artifact'lar) şu kararı verdi: `block.json` -> block (R01, R03), `review.json` -> review (R04), `allow.json` -> allow.

`/explain` (kısaltılmış, `explain_review.json`):
```json
{"transaction_id": 91000001,
 "facts": {"decision": "review", "decision_source": "R04", "final_score": 1.0,
           "anomaly_score": 0.913, "adjusted_score": 0.9477,
           "layer_scores": {"multivariate": 0.461, "entity": 0.863, "column": 0.999, "temporal": 0.999},
           "thresholds": {"score_review": 1.0696, "boost_min": -0.1, "boost_max": 0.4},
           "context_rules": [{"id": "C3", "factor": 0.95}, {"id": "C8", "factor": 1.15}, {"id": "C9b", "factor": 0.95}],
           "triggered_rules": [{"id": "R04", "decision": "review"}], "suppressed_rules": [],
           "reasons": ["Yeni kart (D1=0) ile yüksek tutar: 694.99 USD (eşik 441.95)."],
           "summary": "Karar: review (kaynak: R04, nihai skor 1.000). ..."},
 "narrative": null, "llm_status": "timeout",
 "agent": {"status": "degraded", "plan_source": "default", "errors": ["explainer:explain: ... no answer within 60s"]},
 "trace": ["..."], "latency_ms": 60227}
```
Bu örnek, LLM süresi dolunca `facts`'in tam döndüğünü gösterir (Ollama o sırada önceki bir isteğin sorgusuyla meşguldü). LLM zamanında yanıt verdiğinde `narrative` doludur: `{"label": "destek bilgisi", "text": "...", "grounded": true, "abstained": false, "sources": [...], "affects_decision": false}`, `llm_status="ok"`.

Geçersiz kural seti (`rules_invalid.json`) -> 422:
```json
{"error": {"code": "invalid_rule_set", "message": "The rule set is invalid.",
  "details": [{"rule": "X01", "field": "priority", "message": "Input should be greater than or equal to 1"},
              {"rule": "X01", "field": "severity", "message": "Input should be 'low', 'medium', 'high' or 'critical'"},
              {"rule": "X01", "field": "condition.all.0.op", "message": "Input should be '>', '>=', ..."},
              {"rule": "X01", "field": "action.decision", "message": "Input should be 'block', 'review' or 'allow'"}],
  "request_id": "..."}}
```
Eksik zorunlu alan: `{"error": {"code": "validation_error", "details": [{"field": "card1", "message": "Field required", "type": "missing"}, ...]}}`, HTTP 422.

## facts / narrative ayrımı (K-40)
`facts` koddan gelir ve LLM'e bağlı değildir; rakamlar yalnızca burada otoritedir. `narrative` LLM metnidir ("destek bilgisi", karara etkisiz). Neden: 7B model bağlamı yanlış özetleyebiliyor (Adım 9 demo örneği). `llm_status`: `ok`, `unavailable` (Ollama/embedding kapalı), `timeout` (60 sn), `empty` (LLM kullanılabilir metin üretmedi), `error`. Bunlarda `narrative=null` ve HTTP 200; `/explain` ve `/rag/query` 500 vermez. Ollama kapalıyken `/score` etkilenmez (`/score` yolunda LLM nesnesi hiç çağrılmaz; test sahte LLM'in çağrılmadığını doğrular).

## Online yol ve batch = online tutarlılığı
- `/score`: `FeaturePipeline.transform_one` (batch ile aynı feature kodu) -> `ScoringService.score_one` -> `ContextAdjustEngine.adjust_one` -> `RuleEngine.evaluate`. Entity geçmişi (Adım 3 `EntityStore`, Adım 4 saat deposu) açılışta `artifacts/` snapshot'ından (fit + holdout) yüklenir ve her yeni işlemle büyür.
- Tutarlılık testi (`python -m src.api.consistency`, tam veri): holdout'tan 20 işlem (5 block, 5 review, 10 allow; holdout'a yayılmış), geçmiş fit sonuna sarılıp holdout sırayla işlenerek `/score` koduyla skorlandı ve `reports/rules/rule_hits.parquet` ile karşılaştırıldı. Sonuç: anomaly, adjusted, final ve dört katman skorunda en büyük mutlak fark 0.0 (tolerans 1e-3); karar ve tetiklenen kural listesi 20/20 aynı. Aynı kontrol `tests/api/test_batch_online_consistency.py` içinde sentetik veriyle koşar. R03 cooldown'u kontrol dışıdır (çevrimiçi depo boş başladığı için batch'te cooldown ile silinen satırlar atlanır).

## Gecikme ölçümü
Makine: MacBook (Darwin 24, tek süreç, `make api`), tam veri artifact'ları, yerel Ollama (`qwen2.5:7b`, `bge-m3`). `python -m src.api.loadtest --score 200 --explain 6`, ardışık istekler, HTTP dahil duvar saati. Her istek yeni TransactionID.

| Endpoint | n | p50 | p95 | max |
|---|---|---|---|---|
| `/score` | 200 | 186,5 ms | 264,5 ms | 357,4 ms |
| `/explain` (LLM açık) | 6 | 44,7 sn | 52,0 sn | 52,0 sn |

`/score` hedefi (< 1 sn) karşılanıyor. `/explain` süresinin neredeyse tamamı Ollama'dadır (planlayıcı gerekmeyen varsayılan planda bile RAG cevabı 16-50 sn); süre 60 sn'yi aşarsa `facts` ile `llm_status="timeout"` döner. Ölçüm küçük ve ardışıktır (eşzamanlı yük yok); `/explain` sayıları LLM kuyruğuna ve makineye bağlıdır.

## Pipeline ve make hedefleri (K-43)
`make pipeline` = `profile -> features -> score -> context -> rules` (Adım 1-7), her biri kendi hedefiyle de çalışır. `make rag-index` ayrıdır (Ollama gerekir), `make api` uvicorn'u başlatır (`127.0.0.1:8000`). Eski `index` adımı (var olmayan `scripts/build_index.py`) ve `make index` kaldırıldı; `score` adımı `scripts/run_scoring.py`'yi gerçekten çalıştırır (doğrulandı).

`SAMPLE_N=50000 make pipeline` baştan sona hatasız çalıştı: toplam 46,6 sn (profile ~22 sn, features ~2 sn, score ~10 sn, context ~5 sn, rules ~8 sn).

## Testler
`tests/api/` (50 test): TestClient + `container.<provider>.override` ile sahte LLM/RAG; tüm endpoint'ler; 422 (eksik alan, tür, negatif tutar, bilinmeyen alan, geçersiz kural seti, `k` sınırı); Ollama/embedding kapalı; zaman aşımı; `/score`'da LLM'in çağrılmaması; idempotent cooldown (aynı ID iki kez -> durum bir kez); `request` kural setinin durumu yazmaması; `/explain`'de LLM olmadan dolu `facts`; yanıt/örneklerde etiket alanı yok; alt katmanlar `src.api` import etmez; örnek dosyalar şemaya uyar.

## Bilinen sınırlar
- **Bellek içi store:** entity geçmişi ve cooldown durumu tek süreçte, bellekte. Yeniden başlatınca snapshot'a döner (o ana kadar `/score` ile eklenenler kaybolur). Birden çok worker her biri kendi geçmişini tutar ve tutarsız olur; `make api` tek worker'dır. Gelecek iş: Redis (paylaşımlı, kalıcı store) ve ayrı bir "işlem kaydı" endpoint'i.
- **Sıra dışı işlem:** geçmişten eski `TransactionDT` skorlanır ama `out_of_order_transaction` uyarısı alır (pencere feature'ları yalnızca eklenme sırasındaki geçmişi görür). Örnek istekler holdout'un gerçek zamanını taşıdığı ve snapshot holdout'u içerdiği için bu uyarıyı verir; üretimde zamanla artan `TransactionDT` beklenir.
- **İdempotency önbelleği sınırlı** (5000 sonuç, 256 tam kayıt, `configs/api.yaml`); önbellekten çıkan bir ID tekrar gelirse yeniden skorlanır ve entity geçmişine ikinci kez eklenir (cooldown deposu kendi ID kümesiyle bunu ayrıca engeller, K-27).
- `/explain` ve `/rag/query` bloklayan çağrılardır (K-36); LLM zaman aşımında arka plan thread'i HTTP timeout'una kadar yaşar ve Ollama'yı meşgul tutabilir (ardışık istek gecikebilir).
- Geçersiz kural seti yanıtı yalnızca şema hatalarını gösterir; bilinmeyen feature/param adları şema geçtikten sonra ayrı bir 422 olarak döner.
- Gecikme ölçümü tek makinede, ardışık ve küçüktür; eşzamanlı yük testi yapılmadı. Kimlik doğrulama, rate limit ve TLS yok.
- `/agents/analyze` (skill'de opsiyonel) yazılmadı; `/explain` agent akışını çalıştırır ve trace döner.
