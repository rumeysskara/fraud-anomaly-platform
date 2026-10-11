# Adım 0 Review

Sonuç: GEÇTİ (3 küçük düzeltme önerisi, bloklayıcı yok)

| # | Kontrol | Durum | Kanıt |
|---|---------|-------|-------|
| 1 | make test | ✅ | 13 passed in 1.84s |
| 2 | make lint (ruff + black) | ✅ | All checks passed; 24 files unchanged |
| 3 | isFraud yalnızca loader/evaluation | ⚠️ | src/evaluation/metrics.py:1, src/data/loader.py:3 (docstring) geçerli; configs/settings.yaml:14 `label_column: isFraud` (kod değil, ad konfigü). Loader `y = df.pop(label_col)` ile ayırıyor, X'e girmiyor |
| 4 | Zamansal sızıntı | n/a | Adım 3+ |
| 5 | Zaman split %80/%20, SAMPLE_N | ✅ | loader.py split_by_time (sort stable, cut=int(n*0.8)); load_data önce sort, sonra head(N); testler test_split_by_time, test_sample_n_takes_earliest, test_sample_n_env |
| 6 | Arayüzler kural dosyasıyla uyum | ⚠️ | Detector, Aggregator, RuleEvaluator, Retriever, LLMClient uyumlu. ContextAdjuster.adjust interfaces.py:42 `list[AdjustedResult]` döndürüyor; kural `-> AdjustedResult`. Embedder, BaseAgent ek (ekleme, sorun değil) |
| 7 | Container boş, dependency_injector | ✅ | container.py: DeclarativeContainer, yalnızca `config = providers.Configuration()`, settings.yaml yükleniyor |
| 8 | Seed 42 | ⚠️ | config.py:16 SEED=42 ve settings.yaml seed:42 çift kaynak; set_seed yamlden okumuyor. Değer doğru |
| 9 | Dosya alanı ihlali | ✅ | Beklenmeyen dosya yok; src/ yapısı, scripts/run_pipeline.py, configs/settings.yaml, Makefile, pyproject beklenen kapsamda |
| 10 | docs/step0.md | ✅ | Çıktı, şema, sonraki girdi, sınırlar, isFraud notu var |
| 11 | docs/decisions.md | ✅ | Şablon var, kayıt yok (Adım 0'da önemli karar yok) |
| 12 | README notu | ✅ | README.md:6 tam metin mevcut; kurulum, veri, testler var; Ollama bölümü bilerek boş |
| 13 | Katman bağımlılık yönü | ✅ | src içinde yalnızca src.core importları (grep); döngü yok. evaluation/data core'a bağlı |
| 14 | Her modül için pytest | ⚠️ | core(config/container/interface), loader, metrics testli; container.override testi yok (Adım 0'da zorunlu değil) |
| 15 | Tam veri / süre-bellek | ⚠️ | data/raw boş, gerçek veriyle denenmedi (step0.md'de belirtilmiş). Loader tam CSV okuyup sonra kesiyor |

## Düzeltme önerileri (önem sırası)
1. ContextAdjuster dönüş tipi: kural dosyası tek `AdjustedResult`, kod `list[AdjustedResult]`. Ya kural dosyasını güncelle (toplu batch için mantıklı) ya arayüzü hizala; Adım 6'dan önce karar ver (kullanıcı kararı).
2. split_by_time varsayılanları (0.8, "TransactionDT") hardcoded; settings.yaml split.fit_ratio ile çift kaynak. Çağıranlar yamldan geçirmeli ya da fonksiyon ayarı okumalı. SEED için aynı durum.
3. step0.md'de CLAUDE.local.md'nin istediği "Görüşmede nasıl anlatırım" özeti (3-5 madde + 2 soru-cevap) yok.
4. Git: Adım 0 dosyalarının tamamı commitsiz (git status); docs-delivery.md adım başına commit ister. Commit yapılmadı (review kapsamı dışı).
5. SAMPLE_N için tam CSV okuma sınırı Adım 1'de gerçek veriyle ölçülmeli (nrows/usecols veya chunk).
