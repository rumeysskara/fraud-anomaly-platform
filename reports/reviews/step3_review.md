# Adım 3 Denetim Raporu (step-reviewer)

**Sonuç: GEÇTİ.** Blocker ve major bulgu yok, 4 minor bulgu ve 1 doğrulanmamış iddia var.

## Kontrol sonuçları

| Kontrol | Sonuç | Kanıt |
|---|---|---|
| `make test` | geçti | 74 test; `tests/features/` altında 21 test |
| `make lint` | geçti | ruff ve black temiz |
| isFraud sızıntısı | geçti | `src/features/` etiketi okumuyor; `features.parquet` (271 kolon) ve `merged.parquet` (433 kolon) şemasında `isFraud` yok |
| Geçmiş-only | geçti | `history.py`: `cumsum - y`, `shift(1)`, `searchsorted`; `tests/features/test_no_leakage.py` |
| Fit/score ayrımı | geçti | `fit_stats` yalnızca fit kümesini kullanıyor (n_fit = 472.432, q10 = 25,95) |
| Batch = online | geçti | 400.000 satırlık store sonrası 150 satır `transform_one` ile `features.parquet` karşılaştırıldı: 271 kolonda 0 fark |
| Brute-force geçmiş kontrolü | geçti | 200 rastgele satırda `ent_txn_count`, `ent_cnt_24h`, `ent_sum_24h`, `small_amt_streak_1h` ham veriden yeniden hesaplandı: 0 fark |
| İlk işlem | geçti | `is_first_seen == 1` olan 39.974 satırda geçmiş sayımları 0 |
| Dosya alanı | geçti | `interfaces.py` değişmedi; `container.py` yalnızca ekleme (`feature_pipeline`) |
| Katman yönü | geçti | `features` yalnızca `src.core.config` import ediyor |
| Katalog `model_input` | geçti | `is_holiday` ve `days_to_nearest_holiday` false, diğer 269 kolon true |
| Sezon penceresi | geçti | veriden öğrenildi (29 günlük taban): 2017-12-19..26; 1,83x. 7 günlük taban yerine 29 günlük taban gerekçesi `docs/step3.md` ve K-10'da yazılı |
| `docs/step3.md` | geçti | ne/neden, şema, sonraki adım, sınırlar, "isFraud kullanıldı mı: hayır", varsayımlar, H = yaklaşık kart grubu |
| `docs/decisions.md` K-06..K-10 | geçti | Karar / Alternatifler / Neden biçiminde |
| Kişisel çalışma notları | geçti | kişisel çalışma notları .gitignore'da (repo dışı) |
| README notu | geçti | `README.md:6` |
| Type hint / docstring | geçti | public fonksiyonlarda var; dosyalar 400 satırın altında |

## Bulgular

**Blocker:** yok. **Major:** yok.

**Minor**

| # | Bulgu | Karar |
|---|---|---|
| 1 | `scripts/build_features.py:55` `df.drop(columns=["isFraud"], errors="ignore")` içeriyor; kural `scripts/` altında `isFraud` geçmemesini bekliyor | Düzeltilecek: satır silinecek |
| 2 | `history.py:127,179` `if name == "1h"` sabiti; `small_amt_streak` penceresi config'ten bağımsız | Düzeltilecek: `small_amount.window` config'e taşınacak |
| 3 | Küçük sabitler kodda: `999`, `max(3, baseline_days // 3)`, `ID_COLUMNS_HINT`, `NUMERIC_INPUTS` | Bilinçli olarak bırakıldı |
| 4 | `pipeline.py:3` docstring'i `calendar.py` diyor, dosya `timecal.py` | Düzeltilecek |
| 5 | "Eşik 1,20–1,30 aralığında aynı pencere çıkar" iddiası için rapor/test yok | Düzeltilecek: `reports/features/season_threshold_sensitivity.csv` ve test |

**Not:** `amt_zscore_ent` uç değerleri (−3138 … 2624) ve `amt_ratio_to_ent_avg` Adım 4'te kırpma kararı gerektirecek (`docs/step3.md` "Kırpma yok" diyor).

## Karar kaydı

Kullanıcı bulgu 1, 2, 4 ve 5'in düzeltilmesine, bulgu 3'ün kalmasına karar verdi. Düzeltmeler sonrası `make test` ve `make lint` yeniden çalıştırılır.
