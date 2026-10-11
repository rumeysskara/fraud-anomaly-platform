# Fraud & Anomaly Detection Platform

## Amaç
IEEE-CIS (train_transaction.csv + train_identity.csv, TransactionID ile join) üzerinde
çok katmanlı anomali tespiti, context-aware skor düzeltme, configurable rule engine,
local-LLM RAG ve multi-agent orkestrasyon; FastAPI ile servisleştirilir.
Değerlendirme GitHub reposu üzerinden yapılır: kod, teknik doküman, README.

## İki farklı "agent" kavramı (karıştırma)
- `.claude/agents/*.md` = GELİŞTİRME agent'ları (Claude Code subagent'ları). Kodu yazarlar.
- `src/agents/` = ÜRÜNÜN İÇİNDEKİ runtime agent'lar (Adım 9). Local LLM ile çalışır, API'den çağrılır.
Teknik dokümanda yalnızca `src/agents/` anlatılır.

## Teknoloji kararları (değiştirme)
- Python 3.11, pandas/pyarrow (ara çıktılar parquet), scikit-learn, joblib
- API: FastAPI + pydantic v2
- DI: `dependency_injector` (tüm servisler src/container.py içinde)
- LLM/Embedding: sadece local (Ollama). Ücretli API YOK.
- Vector store: FAISS (local)
- Kurallar: YAML (configs/rules.yaml), JSON da kabul edilir; kod içine hardcode edilmez

## Proje genelinde sabit kararlar (her agent aynısını kullanır)
- **Referans tarih**: `TransactionDT` saniye cinsinden ofsettir; datetime = 2017-12-01 00:00:00 + TransactionDT.
  Bu bir varsayımdır, dokümanda böyle belirtilir.
- **Zaman bazlı split**: TransactionDT'ye göre sıralı ilk %80 = fit, son %20 = holdout.
  Model/istatistik fit kümesinde öğrenilir, metrikler holdout'ta raporlanır. Rastgele split YOK.
- **Geliştirme modu**: `SAMPLE_N` ortam değişkeni (örn. 50000) verilirse loader zamana göre ilk N satırı alır.
  Kod önce örneklemle çalıştırılır, sonra tam veriyle. Testler hiçbir zaman gerçek veriye bağlı değildir.
- **Seed**: 42 (numpy, sklearn, random, faiss).
- **Entity proxy**: user_id yok; proxy Adım 1-2'de önerilir, Adım 3'te `configs/entity.yaml` içine yazılır,
  sonraki herkes oradan okur.

## IEEE-CIS'e özel kurallar
- `isFraud` etiketi anomali skorlamada, feature üretiminde, ağırlık/eşik/kural seçiminde KULLANILMAZ.
  Yalnızca `src/evaluation/` içinde değerlendirme (PR-AUC, recall@k, FP oranı) için okunur.
- Bellek: dtype downcast + parquet; ~590k satır x ~430 kolon.
- Yüksek cardinality: card1, addr1, P_emaildomain, R_emaildomain, DeviceInfo, id_30-33...
  one-hot yapma; frequency / count encoding kullan. Target encoding yok.

## Mimari kuralları
- Ortak arayüzler `src/core/interfaces.py` içinde (Adım 0'da oluşturulur, sonra genişletilir).
- Her detector: `fit(df)`, `score(df) -> pd.Series [0,1]`, `explain(row) -> dict` (Strategy).
- Batch (parquet) ve online (tek işlem, API) yolu AYNI kodu kullanır. Fit edilmiş nesneler
  `artifacts/` altına kaydedilir; API istek anında eğitim yapmaz.
- Tüm servisler container'dan inject edilir; servis içinde bağımlılık oluşturma ve global state yok.
- Skorlar [0,1]; ham skor da saklanır. Her skor için açıklama üretilir.

## Kod standartları
- Type hint zorunlu, public fonksiyonlarda docstring. ruff + black (pyproject.toml).
- Her modül için en az bir pytest, küçük sentetik veriyle.
- Notebook yok; analizler `scripts/` altında, çıktılar `reports/` altına.
- Pipeline tek komutla çalışır: `make pipeline` (veya `python scripts/run_pipeline.py`).

## Agent çalışma düzeni
- Her geliştirme agent'ı yalnızca kendi dosya alanına yazar (agent tanımında listeli).
  `src/container.py` ve `src/core/interfaces.py` ortak dosyalardır: yalnızca EKLEME yapılır, mevcut kayıt silinmez.
- Adım bitince: `make test` geçmeli, `docs/stepN.md` yazılmalı, step-reviewer ile kontrol edilmeli.
- Sıra: platform-architect (Adım 0) -> data-profiler -> feature-engineer -> anomaly-engineer
  -> context-engineer -> rule-engineer -> rag-engineer -> agent-orchestrator -> api-engineer -> docs-writer

## Teslim
- README (kurulum + çalıştırma adımları), docs/technical_doc.md, GitHub repo
- Teknik doküman Adım 6 ve 7'yi detaylı anlatır: kural tasarımı, öncelik,
  conflict resolution, anomali tespitine ve false positive'e etkisi (önce/sonra metrik)
