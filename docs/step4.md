# Adım 4 - Anomali katmanları

**isFraud kullanıldı mı: hayır - yalnızca evaluation'da raporlama.** Katmanlar (fit, kırpma sınırları, ECDF'ler, IF, geri çekme, normalizasyon tabloları) etiketi hiç görmez. `src/detection` ve `src/scoring` içinde `isFraud` geçmez (testle doğrulanır: `tests/scoring/test_no_label_use.py`). Etiket yalnızca `scripts/run_scoring.py` içindeki `evaluate_holdout` fonksiyonunda loader ile okunur ve `src/evaluation/metrics.py` ile PR-AUC / ROC-AUC / recall@k hesaplanır.

## Ne yapıldı
Dört katman `Detector` arayüzünü (`fit`, `score` -> [0,1], `explain`) uygular. Ortak taban sınıf `LayerDetector` (src/detection/base.py): `_fit_stats` fit kümesinden istatistik öğrenir, `raw_score` sınırsız ham skoru verir, `score` fit kuantil tablosuyla normalize edilmiş [0,1] skoru verir (Adım 5). Katmanlar `build_detector`/`build_all` Factory'siyle `configs/anomaly.yaml`'dan kurulur. Seed 42, split `configs/settings.yaml`'dan (ilk %80 fit, `split_by_time`).

| Dosya | İçerik |
|---|---|
| `src/detection/tails.py` | `TailScorer`: fit ECDF'inden `-log10(p)` (iki yönlü / üst / alt / ayrık) |
| `src/detection/preprocess.py` | `RobustPreprocessor`: sentinel -> NaN, işaretli log, p0.1/p99.9 kırpma, medyan + `__na` bayrağı (K-11) |
| `src/detection/column.py` | `ColumnDetector` (K-12) |
| `src/detection/multivariate.py` | `MultivariateDetector`, yalnızca Isolation Forest (K-13) |
| `src/detection/entity.py` | `EntityDetector`, yumuşak geri çekme (K-14) |
| `src/detection/temporal.py`, `hour_history.py` | `TemporalDetector`, entity-saat geçmişi ve `HourStore` (K-15) |
| `src/detection/aux.py` | `build_aux`: ham kayıttan `entity_key` (card1+addr1) ve `has_device` |
| `src/detection/factory.py` | Factory + IF-core/IF-full kolon seçimi (K-13, K-18) |
| `configs/anomaly.yaml` | tüm parametreler ve column listesi |

## Girdi
`data/processed/features.parquet` (Adım 3) + `reports/features/feature_catalog.parquet` (`model_input`, grup). features.parquet'te entity anahtarı ve ham DeviceInfo yok; `build_aux` bunları ham kayıttan (`merged.parquet`: card1, addr1, DeviceInfo, batch'te; API payload'ı, online'da) üretir ve feature'lara eklenir. Satırlar zaman sıralıdır; fit = ilk %80, holdout = son %20 (`split_by_time`).

## Katmanlar

### Column (K-12)
28 açıklanabilir kolon (config): `amt_log`, `amt_n_decimals`, `amt_fit_freq`, `amt_vs_product_q`, `amt_dev_*`, `dist1/2_log`, `freq_*` (8), C1, C2, C6, C11, C13, C14, D4, D10, D15, `time_since_last_txn`, `amt_ratio_to_ent_avg`, `amt_zscore_ent`. Skor `-log10(2*min(F,1-F))` (iki yönlü, +1 yumuşatma; fit aralığı dışı değer sonlu kalır); few-valued kolonlar (<= 10 değer) `-log10(frekans)`; NaN kendi seviyesidir. Satır = en yüksek 3 kolonun ortalaması. `explain`: en sapan 3 kolon, değeri, kuyruk skoru. Neden 28: tüm 251 kolonda top-3 ortalaması doyar (örneklem holdout'u: skor >= 2 olan satır %39,6 vs %17,4).

### Multivariate (K-13)
Isolation Forest (200 ağaç, max_samples 256, contamination auto, seed 42, n_jobs -1). IF-core girdisi (tam veri): 75 kolon (temporal, entity, relational, context grupları + C + D; pencereli `ent_cnt_*`/`ent_sum_*` dahil, ömür boyu kümülatifler ve `day_index`/`card_start_day` hariç, K-18 düzeltmeli) + fit'te NaN görülen 15 kolon için `__na` bayrağı = 90 giriş (örneklemde 74 + 15). İşaretli log uygulanan kolonlar (|çarpıklık| > 5): tam veride 28 (`reports/scores/mv_logcols.csv`). Ham skor `-score_samples`. `explain`: her feature'ı fit medyanına çekip ham skor düşüşünü ölçer, en büyük 5 katkı. IF-full: + V temsilcileri (460 giriş), yalnızca ablation.

### Entity (K-14)
`skor = w*E + (1-w)*G`, `w = n/(n+5)`. E = ortalama(tutar z-skoru [std=0 -> global std], log tutar/geçmiş ortalama oranı, yeni cihaz); G = ortalama(global tutar kuyruğu, `-log10(freq_DeviceInfo)`, `card_new_addr` nadirliği). Kümülatif kolonlar (`ent_avg_amt`, `ent_std_amt`, `device_ent_match`) yalnızca burada kullanılır; `ent_txn_count` yalnızca `w` içindir. Örneklem holdout'unda ilk işlem %18,2, n < 5 olan %43,1; std = 0 ve n >= 2 olan satır %1,0. `explain`: w, E, G, ham sinyaller. Kapsam dışı: ProductCD sinyali (features.parquet'te yok).

### Temporal (K-15)
Beş alt skor, eşit ağırlık (config): velocity, inter-arrival kısalığı, düşük hacim penceresi, saat nadirliği (entity saat geçmişi, yalnızca önceki işlemler, k=5 ile global saate çekilir), (gün, saat) baseline hacim sapması. Alt skorlar `explain` çıktısında. Entity-saat geçmişi online için `HourStore` (artifacts) ile okunur; batch'te expanding sayımdır, aynı `hour_rarity` fonksiyonu.

## Batch = online
`ScoringService.score_one` tek kaydı 1 satırlık DataFrame yapıp `score_batch` ile aynı kodu çalıştırır (temporal'de yalnızca entity-saat sayımı store'dan okunur). Test: `score_one` = `score_batch` satırı (tüm katmanlar ve toplam), store ile online temporal = batch temporal, geleceğin geçmiş skorları değiştirmediği.

## Çıktılar (örneklem koşusu `reports/scores/sample`, tam koşu `reports/scores`)
| Dosya | Şema |
|---|---|
| `layer_scores.parquet` | index TransactionID; `column_score`, `multivariate_score`, `entity_score`, `temporal_score` [0,1]; ham: `raw_column`, `raw_multivariate`, `raw_entity`, `raw_temporal` |
| `artifacts/detectors/*.joblib` | fit edilmiş 4 detector (örneklemde `artifacts/detectors/sample`) |
| `layer_corr_fit.csv`, `layer_corr_holdout.csv`, `score_summary.csv`, `mv_input.csv`, `mv_logcols.csv` | tanı tabloları |

## Bilinen sınırlar
- Geçmiş bir işlemi yeniden oynatma (replay) batch ile birebir aynı sonucu vermez: `run_scoring.py` saatlik geçmiş deposunu (`HourStore`) fit ve holdout dahil tüm satırlardan kurar. Tam veride `score_one` ile `score_batch` farkı temporal'de en fazla 0,159, `anomaly_score_norm`'da en fazla 0,050 (diğer üç katmanda 0). Yeni bir işlem için eşitlik geçerli ve testlidir; online yolda yalnızca yeni işlemler skorlanır. Kullanıcı kararı: "o ana kadar" mantığıyla yeniden kurulum yapılmaz, sınır olarak kayıtlıdır.
- Örneklem (50k) yalnızca ~13 günü kapsar; holdout ~3 gün, 228 pozitif, metrikler gürültülüdür. Tam veri: fit 472.432, holdout 118.108 satır, 4.064 pozitif.
- Temporal katman diğerleriyle zayıf korelasyonlu, entity ve column ile hafif negatif (tam veri Spearman fit: -0,10 ... 0,27; entity-temporal -0,10, column-temporal -0,01): bağımsız bir sinyal olabilir ama sezonsal etkiler de olabilir.
- Column listesinden hangi C/D'nin seçildiği bir tercihtir.
- `hour`, `local_hour_est` referans-tarih ve yerel saat varsayımlarına bağlıdır (Adım 3).
- **Entity tutar z-skoru (K-56):** Az geçmişli ve tutarları sabit entity'lerde std ~0 olduğundan z-skoru çok büyüyebiliyor (fit'te |z|>50: 1.464 satır). Katmanlar rank tabanlı olduğu için skor patlamıyor ve C4/R10 etkilenmiyor. Gelecek iş: göreli std tabanı max(std, 1 USD, 0,1 × |ortalama|). Ayrıntı: `amt_zscore_ent` paydası `max(std, 1 USD)` (`configs/entity.yaml` `z_std_floor`); entity katmanı z'yi kendisi `std > 0` kontrolüyle yeniden hesaplar, bu yüzden 4,8e-7 gibi float gürültüsü std'ler tabana takılmaz. |z|>50 satırlarının %75'inde std <= 1 ve geçmiş medyanı 2 işlemdir. C4/R10 en az 809 geçmiş işlem istediği için bu satırlara dokunmaz. Uygulanmadı (kullanıcı kararı).
- Sinyal gücü zayıf: tek katman PR-AUC 0,046-0,088 (tam veri holdout taban oranı %3,44). Denetimsiz skorlarda beklenen düzey; ağırlıklar bu sonuçlara göre değiştirilmedi.

## Bir sonraki adımın girdisi
Adım 5 aynı detector'ları `ScoringService` altında birleştirir; Adım 6 `raw_score.parquet` içindeki `raw_anomaly_score`'u okur.
