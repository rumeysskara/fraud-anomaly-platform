# Adım 0: Platform Temeli

## Ne yapıldı
İş mantığı olmadan iskelet ve sözleşmeler kuruldu:
- `pyproject.toml` (ruff + black, satır 100, Python 3.11, pytest), `Makefile` (install, lint, format, test, profile, features, score, pipeline, index, api).
- `src/core/interfaces.py`: `Detector`, `Aggregator`, `ContextAdjuster`, `RuleEvaluator`, `Embedder`, `Retriever`, `LLMClient`, `BaseAgent` (ABC).
- `src/core/types.py`: pydantic modeller `ScoreResult`, `AdjustedResult`, `RuleResult`, `Explanation`, `Chunk`, `AgentMessage`.
- `src/core/config.py`: yaml okuma, yol sabitleri (`DATA_DIR`, `ARTIFACTS_DIR`, `REPORTS_DIR`), `SAMPLE_N`, `set_seed`.
- `src/data/loader.py`: `load_data()` -> `(X, y)`, `split_by_time()`, `add_datetime()`.
- `src/evaluation/metrics.py`: PR-AUC, ROC-AUC, precision@k, recall@k, bütçeye göre FP, önce/sonra FP karşılaştırması.
- `src/container.py`: boş `Container` (yalnızca `config`), `create_container()`.
- `scripts/run_pipeline.py`: yazılmamış adımları atlayan iskelet.
- `configs/settings.yaml`.

## Neden
Sonraki tüm adımlar aynı sabitleri, arayüzleri ve veri yolunu kullansın diye.

## Sabit kararlar (configs/settings.yaml)
- Referans tarih (varsayım): datetime = 2017-12-01 00:00:00 + TransactionDT saniye.
- Zaman split: TransactionDT sıralı ilk %80 fit, son %20 holdout; rastgele split yok.
- Seed 42. Alarm bütçeleri: %1 ve %5.

## Çıktı ve şema
- `load_data(data_dir=None, sample_n=None)` -> `X` (index = TransactionID, TransactionDT'ye göre sıralı, isFraud YOK) ve `y` (int8, aynı index). transaction ile identity LEFT JOIN. Float32/küçük int downcast; string kolonlar object kalır.
- `split_by_time(df, ratio=None)` (ratio ve zaman kolonu `settings.yaml`'dan) -> `(fit, holdout)`; y için `y.loc[fit.index]`.
- Metrik fonksiyonları `y` ve `score` Series'ini index ile hizalar.
- `SAMPLE_N` ortam değişkeni: transaction dosyasının ilk N satırı; identity bu TransactionID'lere göre filtrelenir.

## Sonraki adımın girdisi
Data-profiler `load_data` + `split_by_time` kullanır; entity proxy önerisi yapar (karar kullanıcıda, `configs/entity.yaml` Adım 3'te).

## Bilinen sınırlar
- `SAMPLE_N` verilince yalnızca `nrows=N` okunur; bu, dosyanın TransactionDT'ye göre sıralı olduğu varsayımına dayanır (loader okunan satırları yine sıralar). Tam veride bellek ~ birkaç GB.
- Gerçek veri ile `SAMPLE_N` denemesi yapılmadı (`data/raw/` boş); testler sentetik veri kullanır.
- Float32 downcast TransactionAmt'te küçük hassasiyet kaybı yapar.
- Adım scriptleri (profile_data.py vb.) henüz yok; pipeline bunları atlar.

## isFraud kullanımı
isFraud kullanıldı mı: hayır (modelleme/feature için). Yalnızca `src/data/loader.py` içinde ayrı `y` olarak ayrıldı ve `src/evaluation/` içinde metrik hesabı için okunur. Başka yerde kullanılmadı.
