# Adım 3 - Feature engineering

**isFraud kullanıldı mı: hayır.** Hiçbir feature, eşik, frekans tablosu veya pencere seçiminde etiket okunmadı. `merged.parquet` etiket içermez (loader `y`'yi ayrı tutar); `scripts/build_features.py` ve `src/features/` etiketi hiç yüklemez. EDA'daki etiketli tablolar (docs/eda.md B bölümü) yalnızca makullük kontrolü içindi, hiçbir değer onlardan seçilmedi.

## Ne yapıldı
`FeaturePipeline` (src/features/pipeline.py): `fit(df_fit)` fit kümesinden (zamana göre ilk %80) istatistik öğrenir, `transform(df)` batch (parquet), `transform_one(txn: dict)` online (API) yoldur. Seed 42, referans tarih ve split `configs/settings.yaml`'dan; entity ve feature sabitleri `configs/entity.yaml` (`features:`), tatiller `configs/holidays.yaml`.

| Dosya | İçerik |
|---|---|
| `src/features/timecal.py` | saat, gün, hafta sonu, düşük hacim penceresi, yerel saat tahmini, tatil |
| `src/features/rowwise.py` | tutar, kart yaşı, relational ve context feature'ları (yalnızca o satır + fit istatistiği) |
| `src/features/history.py` | entity geçmişi (yalnızca geçmiş): `batch_history` (vektörel) ve `EntityStore` (online durum) |
| `src/features/learned.py` | fit istatistikleri (`LearnedStats`), V/C/D temsilci seçimi |
| `src/features/catalog.py` | her kolonun adı, grubu, formülü, açıklaması |
| `scripts/build_features.py` | uçtan uca çalıştırma (`SAMPLE_N` destekli); `make features` |
| `tests/features/` | 24 test (aşağıda) |

## Varsayımlar (zorunlu not)
Tüm projenin varsayımları tek tabloda: [assumptions.md](assumptions.md). Adım 3'e özgü olanlar:
- **Referans tarih:** datetime = 2017-12-01 00:00:00 + TransactionDT. Bu bir **varsayımdır**; gün adları, hafta sonu ve tatil feature'ları buna bağlıdır.
- **Saat dilimi / yerel saat:** gerçek saat dilimi bilinmiyor. Fit'te hacmin en düşük olduğu ardışık 6 saat (referans saatle 06:00-11:59, fit hacminin %4,07'si) yerel 00:00-06:00 kabul edilir; `local_hour_est = (hour - 6) mod 24`. Ofset config'te görünür (`learned.local_offset_hours: -6`; `features.local_time.offset_override_hours` ile elle verilebilir). `is_business_hours` = yerel 09-18 ve yerel hafta içi. Bu bir tahmindir, kanıtlanmamıştır.
- **is_weekend** referans takvimine göre üretilir (lag-7 otokorelasyonu 0,38 ile haftalık döngü zayıf-orta). Yerel takvimle (-6 saat kaydırılmış) satırların %6,3'ünde farklıdır (`reports/features/weekend_ref_vs_local.csv`); yerel takvim feature olarak eklenmedi.
- **addr2 = 87 = ABD** topluluk yorumudur (resmi değil). `foreign_addr2`: addr2 dolu ve fit'teki en sık değerden (87) farklı. Tatil listesi de ABD resmi tatilleridir.
- **holiday_season penceresi** tek bir Aralık'tan öğrenildi (aşağıda); başka yıllara genellenmez.
- **Entity H = card1 + addr1 "yaklaşık kart grubu"dur, kişi değildir** (K-05). Aynı gruba birden çok kart düşebilir (docs/step2.md D1n sabitlik kontrolü); tüm `ent_*` feature'ları bu gruba aittir. addr1 NaN ayrı seviyedir.
- **Kart yaşı** = D1 (`card_age_days`), `is_new_card` = D1 == 0, `card_start_day` (D1n) = TransactionDT // 86400 - D1. Yorum veriyle desteklenir, kanıtlanmamıştır (K-05).

## Feature'lar (271 kolon = 62 elle tasarlanmış + 209 ham)
Tam liste: `reports/features/feature_catalog.parquet|csv` (ad, grup, formül, açıklama, `model_input`, `model_input_note`); `model_input = false` olanlar: `is_holiday`, `days_to_nearest_holiday` (K-10); özet (null payı, ortalama, min, max): `feature_summary.csv`. Velocity feature'ları "entity" grubundadır.

| Grup | Sayı | Feature'lar |
|---|---|---|
| temporal | 10 | hour, day_of_week, is_weekend, day_index, is_low_volume_window, local_hour_est, is_business_hours, is_holiday, holiday_season, days_to_nearest_holiday |
| entity (geçmiş + velocity + kart) | 24 | is_first_seen, ent_txn_count, ent_avg_amt, ent_std_amt, ent_max_amt, amt_ratio_to_ent_avg, amt_zscore_ent, ent_age_days, ent_unique_device, ent_unique_email, time_since_last_txn, avg_inter_arrival, ent_cnt_{1h,6h,24h,7d}, ent_sum_{1h,6h,24h,7d}, small_amt_streak_1h, card_age_days, is_new_card, card_start_day |
| relational | 7 | card_new_addr, device_ent_match, has_recipient, email_mismatch, foreign_addr2, addr2_missing, os_browser_rare |
| context | 21 | amt_log, amt_n_decimals, amt_has_3dec, amt_fit_freq, amt_is_common, amt_vs_product_q, amt_dev_card4_card6, amt_dev_addr1, has_identity, dist1/2_missing, dist1/2_log, freq_{card1, addr1, P_emaildomain, R_emaildomain, DeviceInfo, id_30, id_31, id_33} |
| passthrough | 209 | ham V (185), C (13), D (11): redundancy_clusters temsilcileri + küme dışı kolonlar; V sayısal, NaN korunur |

### Case'teki "user" feature'larının karşılığı
Veride user_id yoktur. "User" yerine entity proxy H = `card1 + addr1` kullanılır (K-05): bu bir kart grubudur, kişi değildir.
Case'teki örnek adlar repoda `ent_` önekiyle yer alır. Hepsi yalnızca geçmiş işlemlerden hesaplanır (`shift(1)`, satırın kendisi sayılmaz).

| Case'teki ad | Repodaki feature | Tanım (feature_catalog.csv) |
|---|---|---|
| user_avg_amount | `ent_avg_amt` | Entity'nin geçmiş işlemlerinin ortalama tutarı (expanding mean, shift(1)); geçmiş yoksa fit genel ortalaması |
| user_transaction_count | `ent_txn_count` | Entity'nin bu işlemden önceki işlem sayısı |
| user_std_amount | `ent_std_amt` | Geçmiş tutarların std'si; 2'den az geçmiş işlemde fit genel std'si |
| user_max_amount | `ent_max_amt` | Geçmiş en yüksek tutar; geçmiş yoksa 0 |
| amount / user_avg_amount | `amt_ratio_to_ent_avg`, `amt_zscore_ent` | Tutarın entity'nin geçmiş ortalamasına oranı ve z-skoru |
| user velocity (son 1s/6s/24s/7g) | `ent_cnt_{1h,6h,24h,7d}`, `ent_sum_{1h,6h,24h,7d}` | Penceredeki geçmiş işlem sayısı ve toplam tutar |
| time since last transaction | `time_since_last_txn`, `avg_inter_arrival` | Önceki işlemden bu yana geçen saniye; geçmiş işlemler arası ortalama süre |
| user account age | `ent_age_days` | Entity'nin ilk işleminden bu yana geçen gün |
| user device / e-mail count | `ent_unique_device`, `ent_unique_email` | Entity'nin daha önce kullandığı farklı cihaz / e-posta alanı sayısı |

Önemli tanımlar:
- **Düşük hacim penceresi:** `is_low_volume_window` = (hour - başlangıç) mod 24 < 6; başlangıç fit'ten `argmin` ile (K-06).
- **Velocity:** pencereler 1h/6h/24h/7d (sayım + toplam tutar); bir geçmiş işlem `event_dt >= dt - pencere` ise sayılır, satırın kendisi ve sonraki satırlar sayılmaz (K-07). 30 gün yok.
- **Card testing:** `small_amt_streak_1h` (pencere `features.small_amount.window` config'inden okunur, velocity pencerelerinden biri olmalı, değilse hata verir; özellik adı `small_amt_streak_<pencere>`) = entity'nin son 1 saatteki geçmiş işlemlerinden tutarı <= fit q10 (25,95 USD) olanların sayısı (K-08).
- **Tutar:** `amt_n_decimals` (0-3; 3 ondalık = olası döviz çevrimi, topluluk yorumu: tam veride satırların %10,5'i, bunların %95'inde addr1 boş); `amt_fit_freq` = aynı tutarın (sente yuvarlanmış) fit'teki payı, görülmemişse 0; `amt_is_common` = fit'te en sık 20 tutardan biri (59, 117, ...); `amt_ratio_to_ent_avg` = tutar / entity'nin geçmiş ortalaması.
- **R_emaildomain:** boşluk yapısaldır; `has_recipient` ayrı bayrak. `email_mismatch` yalnızca P ve R ikisi de doluysa 1 olabilir (satırların %21,4'ü).
- **Yabancı ülke:** `foreign_addr2` ve ayrı `addr2_missing`.
- **Tatil:** is_holiday (Noel, Yılbaşı, MLK, Başkanlar Günü, Memorial Day), holiday_season (fit hacminden öğrenilen pencere, K-10), en yakın tatile mutlak gün farkı. Referans-saat tarihine göre eşlenir.
- **card_new_addr:** bilinen card1'in yeni bir addr1 ile ilk kullanımı (entity ilk görülüyor ve card1 daha önce görülmüş).
- **Frequency encoding:** fit payı; fit'te görülmeyen değer = 0, NaN de bir değerdir. One-hot ve target encoding yok.

### Tatil feature'ları ve sezon penceresi (K-10; fit, etiketsiz)
Tablolar: `reports/features/holiday_volume_fit.csv`, günlük oran tablosu `season_detection_fit.csv`.
- **Resmi tatil hipotezi reddedildi.** Fit'te 4 resmi tatil günü (25 Aralık, 1 Ocak, 15 Ocak, 19 Şubat): günlük ortalama 3.388, diğer günler 3.371, oran 1,00. 25 Aralık yüksek (6.065), diğer üçü düşük (2.204-2.982). `is_holiday` ve `days_to_nearest_holiday` features.parquet'te durur ama kataloğda `model_input = false`; Adım 4 model girdisine girmez (`FeaturePipeline.model_input_columns`).
- **Sezon etkisi kabul edildi, pencere veriden öğrenildi.** Kural (`features.holidays.season` config): oran_d = günlük hacim / çevresindeki 29 günün ortalanmış medyanı; oran >= 1,25 olan ardışık günler blok oluşturur; 3 günden kısa bloklar atılır; (oran - 1) toplamı en büyük blok seçilir. Fit'in son (yarım) günü hesaba katılmaz.
- **Seçilen pencere: 2017-12-19 ... 2017-12-26 (8 gün).** Taban çizgisine göre ortalama oran 1,41 (günler 1,33-1,64; en yüksek 23 Aralık 6.852 işlem); pencere günlerinin günlük ortalaması 5.884, diğer fit günleri 3.219 (1,83x). Tarihler `configs/entity.yaml` `learned:` ve `configs/holidays.yaml` `learned_season:` altında görünür; transform fit edilmiş pipeline'daki değeri kullanır. Eşik 1,20-1,30 arasında 0,01 adımla taranınca (11 değer) aynı pencere ve aynı ortalama oran (1,408) çıkar: [season_threshold_sensitivity.csv](../reports/features/season_threshold_sensitivity.csv) (tarama aralığı config'te `season.sensitivity`).
- **Eski sabit pencere (20 Aralık - 2 Ocak) ile fark:** eski pencere 14 gün, diğer günlerin 1,43 katı; öğrenilen pencere 8 gün, 1,83 kat. Eski pencere hacmin düştüğü 27 Aralık - 2 Ocak günlerini de içeriyordu (27 Aralık'ta 3.458 işlem, 1 Ocak 2.982). Eski pencere yalnızca karşılaştırma için raporlanır (`season_fixed_old`).
- **Neden 7 günlük medyan değil:** 7 günlük taban 8 günlük tepeyi göremez (tepe günleri kendi medyanını yükseltir, oran ~1,0) ve aynı kural 92. gündeki tek günlük sıçramayı seçerdi. Taban uzunluğu config'tedir (`baseline_days`); testte 7 günlük tabanın tepeyi bulamadığı gösterilir.
- Sınır: yalnızca tek bir Aralık gözlendi; "sezon" burada "veride gözlenen hacim tepesi"dir, takvimsel Noel kanıtı değildir. Referans tarih varsayımı ile Noel dönemine denk gelmesi örtüşmedir.

## İlk işlem ve sızıntı güvencesi
Geçmişi olmayan satırda (`is_first_seen = 1`): sayım ve pencereler 0, ortalama/std = fit genel ortalaması/std'si, oran 1, z-skor 0 (std için en az 2 geçmiş işlem gerekir), max 0, yaş 0, `time_since_last_txn` ve `avg_inter_arrival` = -1. `amt_zscore_ent` paydası `max(std, 1,0)`; çok küçük std'li entity'lerde z değeri aşırı büyüyebilir (aralık -3138 ... 2624), ileri adımlarda kırpılması gerekebilir. Fit istatistikleri (kantil, frekans, baskın addr2, grup ortalamaları, ürün ECDF'leri, düşük hacim penceresi) yalnızca fit kümesinden öğrenilir ve holdout'a uygulanır; geçmiş-only feature'lar ise tüm veride zaman sırasıyla, satır hariç hesaplanır (holdout satırlarının geçmişi fit + holdout içindeki önceki satırlardır).

## Batch = online
`transform_one` satır-içi feature'larda batch ile aynı kodu çalıştırır (1 satırlık DataFrame); geçmiş feature'lar için `EntityStore` aynı tanımın ayrı (artımlı) bir uygulamasıdır. Eşitlik testleri: stream replay (boş store'dan her işlemi sırayla) = batch; fit sonrası store snapshot'ından online = batch; parquet round trip. Tam veride ayrıca 500.000 satırlık store'dan 2.000 sonraki satır online hesaplanıp `features.parquet` ile karşılaştırıldı: 0 fark (rtol 1e-4, atol 1e-2).

## Çıktılar
| Dosya | Şema |
|---|---|
| `data/processed/features.parquet` | index TransactionID; 271 kolon (62 + 209), bool -> int8, float32; tam veri 590.540 x 271, bellekte 586 MB, diskte 77 MB |
| `artifacts/entity_profiles.parquet` | `level` (entity/card), `key`, `count`, `sum_shifted`, `sumsq_shifted`, `max_amt`, `first_dt`, `last_dt`, `devices_json`, `emails_json`, `events_json` (son 7 günün (dt, tutar) çiftleri); card satırlarında yalnızca `count`. 39.974 entity. Durum, verinin son satırından sonrasıdır. |
| `artifacts/feature_pipeline.joblib` | fit edilmiş `FeaturePipeline` (store hariç) |
| `reports/features/` | feature_catalog, feature_summary, holiday_volume_fit, season_detection_fit, season_threshold_sensitivity, hourly_volume_fit, weekend_ref_vs_local |
| `configs/entity.yaml` | `features:` (sabitler) ve `learned:` (fit'ten gelen: pencere başlangıcı 6, ofset -6, küçük tutar eşiği 25,95, baskın addr2 87, sezon 2017-12-19 ... 2017-12-26, n_fit 472.432) |

`*.parquet`, `artifacts/` ve `data/processed/` .gitignore'dadır; temiz klonda `make features` ile üretilir (girdi: `make profile` çıktısı `merged.parquet`). `container.py` içine `feature_pipeline` provider'ı eklendi (joblib + entity store'u yükler, API eğitim yapmaz).

## Testler (tests/features, 24 test)
Batch = online (üç senaryo), ilk işlem varsayılanları, gelecek satırların geçmiş feature'ları değiştirmemesi (prefix ve gelecekteki tutarı bozma testi), satırın kendi geçmişine girmemesi, pencere sayımı ve küçük-tutar serisinin elle hesaplı değerleri, düşük hacim penceresinin argmin ve gece yarısı sarması, takvim/tatil/öğrenilen sezon/yerel saat, sezon tespiti (8 günlük tepeyi bulur, tek günlük sıçramayı ve düz seriyi atlar, 7 günlük taban bulamaz), katalogda `model_input` bayrağı, eşik taramasında sezon penceresinin sabit kalması, küçük-tutar penceresinin config'ten okunması ve velocity penceresi dışında hata vermesi, hafta sonunun referans takvimine göre olması, relational bayraklar, tutar feature'ları, katalog = çıktı kolonları ve grup minimumları (>= 4/6/4/4), float64 kalmaması, V/C/D temsilci seçimi, config'e `learned:` yazımı, container provider'ı.

## Bilinen sınırlar
- Saat dilimi ve referans tarih varsayımdır; `is_business_hours`, `local_hour_est`, `is_holiday` bu varsayıma bağlıdır. `is_holiday` hacim olarak ayrımcı görünmüyor (model girdisi değil).
- H birden çok kartı birleştirir; `ent_*` kişi değil grup davranışıdır. card1+addr1 içinde `card_new_addr` yeni-addr1 sinyalidir.
- Tutarlar float32 saklanır (merged.parquet); 8.192 USD üstünde 3 ondalık ayrımı güvenilmez, sent eşleşmesi float32 -> sente yuvarlama ile yapılır. Üç ondalıklı tutarlar sente yuvarlandığında çakışabilir.
- `transform_one` saf Python/pandas'tır, ölçülen gecikme ~73 ms/çağrı (küçük DataFrame işlemleri); API'de kabul edilebilir ama optimize edilmemiştir.
- `ent_sum_*` ve `ent_std_amt` batch'te kümülatif toplamdan, online'da artımlı toplamdan hesaplanır; küçük yuvarlama farkları olabilir (testler rtol 1e-4).
- Kırpma yok: `amt_zscore_ent`, `amt_ratio_to_ent_avg` uç değer alabilir.
- Entity store tüm verinin sonundaki durumdur; API'de `transform_one(update=False)` geçmişi güncellemez (kalıcı güncelleme sonraki adımların kararıdır).
- features.parquet'te ham C/D/V dışında M, id_*, kategorik kolonlar yoktur; ihtiyaç olursa `merged.parquet`'ten alınır.

## Bir sonraki adımın girdisi
Adım 4 `data/processed/features.parquet`'i okur (fit/holdout ayrımı yine `split_by_time` ile); model girdisi için kataloğun `model_input == true` kolonlarını kullanır (`FeaturePipeline.model_input_columns`). Online yol için `Container.feature_pipeline`.
