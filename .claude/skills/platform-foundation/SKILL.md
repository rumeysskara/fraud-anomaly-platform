---
name: platform-foundation
description: "Adım 0. Veri işine başlamadan önce proje temelini (pyproject, ortak arayüzler, config loader, boş DI container, data loader + SAMPLE_N, zaman split, evaluation modülü, Makefile, pipeline runner) kurarken kullan."
---

# Platform Foundation (Adım 0)

Amaç: sonraki 8 agent'ın aynı temeli kullanması. Burada iş mantığı YAZILMAZ, sadece iskelet ve sözleşmeler.

## Çıktılar
- `pyproject.toml`: proje metadata, ruff (line-length 100), black, pytest (`testpaths = ["tests"]`) ayarları
- `Makefile`: `install`, `lint`, `format`, `test`, `profile`, `features`, `score`, `pipeline`, `index`, `api`
- `src/__init__.py` ve tüm alt paketlerde `__init__.py`
- `src/core/interfaces.py`: ABC/Protocol tanımları
  - `Detector` (fit, score, explain), `Aggregator`, `ContextAdjuster`, `RuleEvaluator`,
    `Retriever`, `Embedder`, `LLMClient`, `BaseAgent`
- `src/core/types.py`: ortak pydantic modeller (`ScoreResult`, `AdjustedResult`, `RuleResult`, `Explanation`)
- `src/core/config.py`: `configs/*.yaml` okuyan yardımcı, `SAMPLE_N` ve yol sabitleri (`DATA_DIR`, `ARTIFACTS_DIR`, `REPORTS_DIR`)
- `src/data/loader.py`: CSV okuma (dtype kontrollü), LEFT JOIN, `SAMPLE_N` desteği (zamana göre ilk N),
  `y` (isFraud) ayrı döner; `split_by_time(df, ratio=0.8)`
- `src/evaluation/metrics.py`: PR-AUC, ROC-AUC, precision@k, recall@k, alarm bütçesine göre FP sayısı.
  isFraud'u okumaya yetkili TEK yer.
- `src/container.py`: boş `DeclarativeContainer` + `config = providers.Configuration()`; sonraki agent'lar ekler.
- `scripts/run_pipeline.py`: adımları sırayla çağıran iskelet (henüz olmayan adımlar atlanır, log'a yazılır)
- `configs/settings.yaml`: referans tarih (2017-12-01), split oranı (0.8), seed (42), alarm bütçeleri ([0.01, 0.05])
- `tests/core/test_loader.py`: sentetik iki CSV ile join + split + SAMPLE_N testi
- `README.md` iskeleti (başlıklar: Kurulum, Veri, Ollama, Çalıştırma, Testler, Mimari, Doküman)
- `docs/step0.md`

## Kontrol listesi
- [ ] `make install && make test` temiz bir ortamda geçiyor
- [ ] `make lint` geçiyor
- [ ] interfaces.py tüm sonraki adımların arayüzlerini içeriyor
- [ ] Loader `SAMPLE_N=1000` ile gerçek veride hızlı çalışıyor (veri varsa)
- [ ] isFraud yalnızca loader'dan ayrı `y` olarak çıkıyor ve sadece evaluation'da kullanılıyor
