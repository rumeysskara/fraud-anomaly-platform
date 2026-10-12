# Fraud & Anomaly Detection Platform

IEEE-CIS verisi üzerinde çok katmanlı anomali tespiti, context-aware skor düzeltme,
konfigüre edilebilir kural motoru, local-LLM RAG ve multi-agent orkestrasyon; FastAPI ile servisleştirilir.

> Geliştirmede Claude Code kullanılmıştır; mimari ve iş kuralı kararları geliştiriciye aittir. Karar kayıtları: docs/decisions.md

## Kurulum
```bash
python3.11 -m venv .venv && source .venv/bin/activate
make install
```

## Veri
`train_transaction.csv` ve `train_identity.csv` dosyalarını `data/raw/` altına koyun
(Kaggle IEEE-CIS Fraud Detection). Veri repoya eklenmez.
Hızlı geliştirme için: `SAMPLE_N=50000 make pipeline` (zamana göre ilk N satır).

## Ollama
Tüm LLM ve embedding işleri yerel Ollama ile yapılır (ücretli API yok).
```bash
ollama serve                 # ayrı bir terminalde (veya Ollama uygulaması açık)
ollama pull bge-m3           # embedding
ollama pull qwen2.5:7b       # LLM (16 GB RAM'e sığar)
make rag-index               # bilgi tabanını üret, chunk'la, embed et -> artifacts/rag/
python scripts/build_rag_index.py --question "Kart testi hangi koşulda tetiklenir?"
.venv/bin/python -m pytest -m ollama -s tests/rag   # gerçek retrieval testi (hit@k)
```
`make test` Ollama gerektirmez. Ollama kapalıysa RAG servisi yalnızca retrieval sonucu döner
(`llm_unavailable`). Ayrıntı: `docs/step8.md`.

## Çalıştırma
Batch adımları tek komutla sırayla çalışır; her adımın kendi hedefi de vardır (adım numaralarıyla eşleşir):

| Hedef | Adım | Ne yapar |
|---|---|---|
| `make pipeline` | 1-7 | profile, features, score, context, rules sırayla (`SAMPLE_N=50000 make pipeline` hızlı deneme) |
| `make profile` | 1-2 | veriyi yükle, birleştir, profil/EDA |
| `make features` | 3 | feature'lar, `artifacts/feature_pipeline.joblib`, entity geçmişi |
| `make score` | 4-5 | anomali katmanları, normalize toplam skor |
| `make context` | 6 | context-aware skor düzeltme |
| `make rules` | 7 | kural motoru, karar raporları |
| `make rag-index` | 8 | bilgi tabanı indeksi (Ollama gerekir; pipeline'a dahil değildir) |
| `make agents-demo` | 9 | üç işlemle agent akışı demosu |
| `make api` | 10 | FastAPI servisi (`http://127.0.0.1:8000`, Swagger: `/docs`) |

```bash
make pipeline      # önce bir kez (tam veri; SAMPLE_N ile örneklem)
make rag-index     # Ollama açıkken, bir kez
make api           # servisi başlat
```

### API örnekleri
API, `artifacts/` altındaki hazır modelleri ve entity geçmişi snapshot'ını açılışta yükler; istek anında
eğitim yapmaz. Örnek istekler `examples/requests/` altındadır (holdout'tan, karara göre seçilmiş, etiketsiz; yeniden üretmek için `python -m src.api.examples`).
```bash
curl -s localhost:8000/health | python -m json.tool

# /score: LLM çağırmaz, < 1 sn. Aynı TransactionID ikinci kez gönderilirse aynı sonuç döner.
curl -s -X POST localhost:8000/score -H 'Content-Type: application/json' \
     -d @examples/requests/block.json | python -m json.tool

# /explain: facts (koddan) + narrative (LLM, "destek bilgisi") + trace. Ollama gerekir, yoksa narrative=null.
curl -s -X POST localhost:8000/explain -H 'Content-Type: application/json' \
     -d @examples/requests/explain_review.json | python -m json.tool

# /rules/evaluate: isteğe bağlı kural seti; geçersizse 422 ve anlaşılır hata
curl -s -X POST localhost:8000/rules/evaluate -H 'Content-Type: application/json' \
     -d @examples/requests/rules_invalid.json | python -m json.tool

curl -s localhost:8000/rules | python -m json.tool
curl -s -X POST localhost:8000/rules/reload
curl -s -X POST localhost:8000/rag/query -H 'Content-Type: application/json' \
     -d '{"question": "Kart testi hangi koşulda tetiklenir?", "k": 4}' | python -m json.tool
```
Notlar: entity geçmişi bellekte tutulur (tek süreç, yeniden başlatınca snapshot'a döner); `make api`
çoklu worker ile çalıştırılmamalıdır. Ayrıntı ve sınırlar: `docs/step10.md`.

## Testler
```bash
make test
make lint
python -m src.api.consistency   # batch = online kontrolü (holdout'tan 20 işlem; SAMPLE_N ile örneklem)
python -m src.api.loadtest      # çalışan API'ye küçük gecikme testi (p50/p95)
```

## Mimari
Katman yönü: api -> agents -> (rag, rules, context, scoring, detection) -> features -> data.
Ortak arayüzler: `src/core/interfaces.py`; DI: `src/container.py`; sabitler: `configs/settings.yaml`.

## Doküman
- Adım dokümanları: `docs/step*.md`
- Karar kayıtları: `docs/decisions.md`
- Teknik doküman: `docs/technical_doc.md` (son adımda)
