# Adım 6 - Context-aware skor düzeltme (Context Adjust)

**isFraud kullanıldı mı: hayır - yalnızca evaluation'da raporlama.** Kurallar, katsayılar ve eşikler etiketle seçilmedi; fit kümesinden öğrenilen iki değer (q90 tutar, baskın addr2) etiketsizdir. `src/context/` içinde `isFraud` geçmez (testle kontrol edilir). Etiket yalnızca `scripts/run_context.py` içindeki `evaluate_holdout()` fonksiyonunda loader ve `src/evaluation/metrics.py` üzerinden okunur. Holdout sonuçları kuralları değiştirmek için kullanılmadı.

**Tasarımın kaynağı:** Kural listesi, koşullar ve katsayılar kullanıcının verdiği tasarımdır (zaman kısıtı nedeniyle bu adımda seçenek turu yapılmadı). Uygulamada yapılan küçük uyarlamalar aşağıda "Tasarımdan sapmalar" bölümündedir.

> **Güncel durum:** Bu doküman önce ilk tasarımı ve holdout sonucunu, sonra **"Düzeltme"** bölümünde holdout'ta fark edilen sorunun tanım ilkesine dayalı (etiketle değil) düzeltmesini anlatır. İlk tasarımın sonuçları silinmedi (`reports/context/initial_design/`). Üretimde geçerli olan revize tasarımdır: C4 yeniden tanımlandı, C6/C9 dışlayıcı grup, sıralama kırpılmamış skorla, öğrenilmiş parametreler `artifacts/context/`.

## Ne yapıldı
`ContextAdjustEngine` (src/context/engine.py, `ContextAdjuster` arayüzü) Adım 5'in `anomaly_score_norm` skorunu bağlama göre çarpımsal olarak düzeltir. Kurallar kodda değil `configs/context.yaml` içindedir: her kuralın `id`, `group`, `name`, `description`, `type`, `condition`, `factor`, `rationale` alanları vardır.

Akış (Chain of Responsibility, `_core`):
1. `layer_weight` kuralı (C5): temporal katman ağırlığı yarıya indirilip Adım 5 toplamı yeniden hesaplanır, Adım 5'in fit kuantil tablosundan geçirilir; değişim bir çarpan olarak ifade edilir (`yeni_norm / eski_norm`).
2. Çarpımsal kurallar (C1-C4, C6-C9): eşleşen tüm kurallar config sırasıyla çarpılır.
3. Toplam çarpan `[0,5; 1,5]` aralığına kırpılır (`bounds`).
4. Koruma G1 (card testing): `small_amt_streak_1h >= 2` ise toplam çarpan 1,0'ın altına inemez, yani hiçbir düzeltme skoru ham skorun altına indiremez (artışlar engellenmez).
5. `adjusted_score = clip(raw_score x toplam, 0, 1)`.

Koşul dili: `all:` altında `{feature, op, value}` cümleleri (op: `== != >= <= > < in isna notna`); `value: {param: ad}` fit'ten öğrenilen değeri gösterir. NaN bir karşılaştırmayı asla sağlamaz (yalnızca `isna`).

| Dosya | İçerik |
|---|---|
| `configs/context.yaml` | kurallar, sınırlar, koruma, öğrenilecek parametre tanımları, raporlama eşiği |
| `src/context/config.py` | YAML -> `ContextConfig` / `RuleSpec` / `GuardSpec`, doğrulama; ablation varyantı (`variant`) |
| `src/context/conditions.py` | koşul dili |
| `src/context/derive.py` | türetilmiş kolonlar (aşağıda), gerekli girdi listesi |
| `src/context/params.py` | `ContextParams.fit` (yalnızca fit satırları), JSON kaydet/yükle |
| `src/context/inputs.py` | batch girdisi: features + merged (TransactionAmt, ProductCD, addr2) + katman skorları + `email_ent_known` |
| `src/context/engine.py` | `ContextAdjustEngine`: `adjust_batch`, `adjust_one` (aynı `_core`) |
| `src/context/factory.py` | `load_engine` (config + params + Adım 5 `scoring_meta.joblib`); container bunu kullanır |
| `src/context/report.py` | etiketsiz rapor yardımcıları: kural kapsaması, alarm profili, ablation varyantları |
| `scripts/run_context.py` | uçtan uca çalıştırma (`SAMPLE_N` destekli) |
| `tests/context/` | 30 test |

`src/container.py`'ye yalnızca ekleme yapıldı: `context_adjuster = providers.Singleton(load_engine, ARTIFACTS_DIR / "detectors")` (API eğitim yapmaz, öğrenilmiş parametreleri yükler).

## Girdi kolonları
| Kaynak | Kolonlar |
|---|---|
| features.parquet (Adım 3) | `local_hour_est`, `is_weekend`, `is_low_volume_window`, `ent_txn_count`, `ent_age_days`, `ent_cnt_24h`, `amt_zscore_ent`, `device_ent_match`, `amt_has_3dec`, `holiday_season`, `card_age_days` (= D1), `small_amt_streak_1h` |
| merged.parquet (TransactionID ile) | `TransactionAmt`, `ProductCD`, `addr2` (+ `email_ent_known` hesabı için `TransactionDT`, `card1`, `addr1`, `P_emaildomain`) |
| layer_scores.parquet (Adım 4) | `multivariate_score`, `entity_score`, `column_score`, `temporal_score` |
| raw_score.parquet (Adım 5) | `anomaly_score_norm` (düzeltilen skor), `raw_anomaly_score` (sıralamada eşitlik kırıcı) |

Türetilmiş kolonlar (`derive.py`, batch ve tek kayıtta aynı kod):
- `abs_amt_zscore_ent` = |amt_zscore_ent|
- `email_ent_known` = entity bu P_emaildomain'i DAHA ÖNCEKİ bir işlemde kullanmış mı (TransactionDT sırası, satırın kendisi ve sonrası sayılmaz; boş e-posta hiç "bilinen" olmaz). features.parquet'te yoktu, `inputs.py` üretir; online yolda entity store'un e-posta kümesinden gelir.
- `known_device_or_email` = `device_ent_match >= 1` veya `email_ent_known == 1` (ikisi de yalnızca geçmiş)
- `ent_daily_avg` = `ent_txn_count / max(ent_age_days, 1)` (entity'nin geçmiş günlük ortalaması)
- `burst_ratio_24h` = `ent_cnt_24h / ent_daily_avg`
- `dominant_layer` = Adım 5 ağırlıklarıyla en büyük katkı `w_i x s_i` olan katman

Fit'ten öğrenilenler (`artifacts/context/context_params.json`, örneklemde `artifacts/context/sample/`; tam veri, n_fit = 472.432): `amount_high` = TransactionAmt q90 = **277,0**; `dominant_addr2` = **87** (Adım 3'teki değerle aynı, script kontrol eder); revize C4 için `trusted_min_history` = `ent_txn_count` fit q90 = **809**. Örneklemde 250,0 ve 51.

## Kurallar
Tetiklenme payı: kuralın skoru değiştirdiği satırların payı (`reports/context/rule_coverage.csv`, etiketsiz).

| ID | Koşul | Çarpan | Gerekçe (kısa) | Fit payı | Holdout payı |
|---|---|---|---|---|---|
| C1 | `local_hour_est` 09-18, `is_weekend = 0`, `ent_txn_count >= 1` | x0,90 | Yerel iş saatinde, geçmişi olan entity: en az şaşırtıcı durum | %39,0 | %41,4 |
| C2 | `is_low_volume_window = 1`, tutar >= fit q90 | x1,15 | Herkes uyurken büyük tutar: hesap ele geçirme kalıbı | %0,34 | %0,48 |
| C3 | `is_weekend = 1`, `ent_txn_count >= 5` | x0,95 | Yerleşik entity'de hafta sonu alışverişi olağandır (referans tarih 2017-12-01 varsayımı) | %23,8 | %25,5 |
| C4 (ilk) | `ent_txn_count >= 20`, `abs_amt_zscore_ent <= 2`, `known_device_or_email = 1` | x0,75 | Uzun geçmiş + kendi normal tutarı + tanıdık cihaz/e-posta: geri dönen müşteri | %47,8 | %61,1 |
| C4 (revize, güncel) | `ent_txn_count >=` fit q90 (809), `ent_age_days >= 30`, `abs_amt_zscore_ent <= 2`, `known_device = 1` VE `known_email = 1` | x0,75 | Aynı gerekçe; "güvenilir" küçük bir azınlık olmalı (Düzeltme bölümü) | %2,0 | %4,0 |
| C5 | `ent_txn_count >= 5`, `ent_daily_avg >= 1`, `burst_ratio_24h <= 3` | temporal ağırlığı x0,5 (yalnızca skoru düşürürse) | Sık işlem yapan entity için yüksek velocity normal ritimdir (Adım 5: temporal üst %1'in %96'sı tek entity burst'ü) | %31,6 (ort. x0,88) | %28,4 (ort. x0,87) |
| C6a | `addr2` dolu ve != fit baskın değeri (87) | x1,20 | Sınır ötesi işlem (addr2 = 87 = ABD varsayımı) | %0,83 | %0,36 |
| C6b | `addr2` boş ve `amt_has_3dec = 1` | x1,10 | Ülkesi bilinmeyen + kur çevrimi görünümlü tutar | %10,2 | %9,1 |
| C7 | `holiday_season = 1`, `dominant_layer = temporal` | x0,90 | Tatil tepesinde hacim/velocity alarmları kısmen mevsimsel gürültüdür | %0,31 | %0 |
| C8 | `card_age_days = 0` (D1 = 0), tutar >= fit q90 | x1,15 | Kartın ilk gününde büyük alışveriş: çalıntı kart / bust-out kalıbı | %5,7 | %5,3 |
| C9a | `ProductCD = C` | x1,10 | Azınlık, kart-yok (CNP), çoğunlukla ülkesiz dijital kanal | %11,9 | %10,3 |
| C9b | `ProductCD = W` | x0,95 | Ana akım ürün; modellerin "normal"i büyük ölçüde onunla kalibre | %73,2 | %79,3 |

C9 notu: yön fit EDA etiket tablosuyla uyumlu (holdout değil). Değer o tablodan seçilmedi; tablo yalnızca makullük kontrolüdür. Revize tasarımda C6a, C6b, C9a, C9b `exclusive_group: geo_product` grubundadır (Düzeltme bölümü). Yukarıdaki pay sütunları ilk tasarımın koşusudur.
| G1 | `small_amt_streak_1h >= 2` (koruma) | toplam >= 1,0 | Card testing indirimlerle gizlenemez | koşul %1,8 | koşul %1,4 |

Tam gerekçe metinleri config'teki `rationale` alanındadır ve her satırın `applied_adjustments` listesine yazılır.

Notlar:
- **C5 ayrıntısı:** yeni ağırlıklar `{mv 0,35, ent 0,25, col 0,20, temp 0,10}` `WeightedAverage` içinde toplamı 1 olacak şekilde yeniden normalize edilir; sonuç Adım 5'in toplam kuantil tablosundan geçirilip `anomaly_score_norm` ölçeğine döner. Adım 5 kodu değiştirilmedi; ağırlık ve tablo `artifacts/detectors/scoring_meta.joblib`'ten okunur. Kontrol: Adım 4 katman skorlarından yeniden hesaplanan toplam, Adım 5 `anomaly_score_norm` ile birebir aynı (maks. fark 0).
- **C7 holdout'ta hiç tetiklenmez:** öğrenilen sezon (2017-12-19 ... 2017-12-26) fit dönemindedir; holdout son %20'dir. Kural online/gelecek Aralık için config'te durur; holdout ölçümü bu kuralı değerlendiremez.
- **C6b ve C9a aynı satırlara düşüyor:** holdout'ta C6b'nin tetiklendiği satırların %100'ü ProductCD = C; C satırlarının %88'inde C6b de tetikleniyor. Bu satırlar fiilen x1,21 alır.
- **Kapsam geniş:** holdout satırlarının %92,3'ünde toplam çarpan < 1, %4,2'sinde > 1; ortalama toplam 0,77. Sınırlar satırların %5,7'sinde devreye girer.

## Çıktılar
| Dosya | Şema |
|---|---|
| `reports/scores/adjusted_score.parquet` | index TransactionID; `raw_anomaly_score` (Adım 5 ham toplam), `raw_score` (= `anomaly_score_norm`, düzeltilen ham skor), `adjusted_score` [0,1] (çıktı/gösterim), `adjusted_score_unclipped` (= raw_score x toplam; revize tasarımda alarm sıralaması bununla), `adjustment_total` (sınır + koruma sonrası çarpan), `adjustment_unbounded` (çarpanların çarpımı), `guard_active` (int8), `factor_<id>` (her kural için, 1 = uygulanmadı), `applied_adjustments` (liste: `{id, name, factor, reason}`; sınır devreye girerse `BOUNDS`, koruma girerse `G1` kaydı da eklenir) |
| `artifacts/context/context_params.json` | fit'ten öğrenilen değerler + `n_fit` (gitignore'da; `make`/script ile üretilir) |
| `reports/context/fp_comparison.csv` | bütçe başına 3 satır: Adım 5, ilk tasarım, revize tasarım (alarm, FP, precision, recall, PR-AUC) |
| `reports/context/c4_coverage.csv` | C4'ün her koşulunun tek başına ve birlikte fit/holdout kapsaması (etiketsiz) |
| `reports/context/initial_design/` | ilk tasarımın korunmuş sonuçları (fp_impact, ablation, rule_coverage, alarm_composition, score_summary; + sample/) |
| `reports/context/fp_impact.parquet` / `.csv` | budget, score (before/after), alarms, tp, fp, precision, recall, fp_share_of_alarms, pr_auc, roc_auc, rows_at_score_1 |
| `reports/context/ablation.csv` | kind, variant, pr_auc, roc_auc, precision@b, recall@b, fp@b |
| `reports/context/rule_coverage.csv` | kural başına fit/holdout tetiklenme payı ve ortalama çarpan (etiketsiz) |
| `reports/context/alarm_composition.csv` | önce/sonra alarm profili (etiketsiz): uzun geçmişli entity, ilk görülen, koruma aktif, alarm kümesinden çıkan |
| `reports/context/score_summary.csv`, `examples.json`, `holdout_base.csv` | özet, en yüksek 5 skorun açıklaması, holdout boyutu |
| `reports/context/sample/` | aynı dosyalar örneklem koşusu için (+ `adjusted_score.parquet`) |

Parquet dosyaları `.gitignore`'dadır; CSV/JSON sürümleri repoya girer.

Açıklama örneği (`adjust_one` / `applied_adjustments`): `{"id": "C6b", "name": "missing_country_converted_amount", "factor": 1.1, "reason": "No billing country plus a converted amount ..."}`; `AdjustedResult.applied_rules = ["C6b", "C9a"]`, son açıklama satırı `total factor x1.210` ve `guard_active`.

## Değerlendirme yöntemi
- Alarm = holdout skorunun en yüksek %1'i (1.182 işlem) veya %5'i (5.906 işlem), `configs/settings.yaml` bütçeleri. Holdout 118.108 satır, 4.064 pozitif (taban oranı %3,44).
- **Eşitlik kırma:** çarpımsal artış + 1'e kırpma nedeniyle holdout'ta 2.006 satır `adjusted_score = 1,0` alır (önce 25). Bu, %1 bütçesinden büyüktür; eşit skorlar TransactionID sırasıyla seçilirse metrik keyfi olur. Bu yüzden tüm varyantlarda eşit skorlar Adım 5 ham toplamına (`raw_anomaly_score`) göre sıralanır (`report.tie_break_order`). Adım 7 de sıralamada `(adjusted_score, raw_anomaly_score)` kullanmalıdır.

## FP etkisi: önce / sonra - İLK TASARIM (TAM veri, holdout)
| Bütçe | Skor | Alarm | TP | FP | Precision | Recall | FP payı |
|---|---|---|---|---|---|---|---|
| %1 | önce (anomaly_score_norm) | 1.182 | 187 | 995 | 0,158 | 0,046 | %84,2 |
| %1 | sonra (adjusted_score) | 1.182 | 142 | 1.040 | 0,120 | 0,035 | %88,0 |
| %5 | önce | 5.906 | 684 | 5.222 | 0,116 | 0,168 | %88,4 |
| %5 | sonra | 5.906 | 615 | 5.291 | 0,104 | 0,151 | %89,6 |

PR-AUC 0,081 -> 0,078; ROC-AUC 0,683 -> 0,687.

**Sonuç: tasarım holdout'ta yanlış pozitifi AZALTMADI.** %1 bütçede FP +45 (995 -> 1.040), recall 0,046 -> 0,035; %5 bütçede FP +69 (5.222 -> 5.291), recall 0,168 -> 0,151. Kurallar holdout sonucuna göre değiştirilmedi (etiketle ayar yasak); bulgu aşağıda açıklanır ve karar kullanıcıya bırakılır.

Etiketsiz alarm profili (`alarm_composition.csv`): %1 bütçede uzun geçmişli (`ent_txn_count >= 20`) entity alarmları 920 -> 550, ilk görülen entity alarmları 28 -> 50; %5'te 4.778 -> 2.905 ve 98 -> 719. Yani kurallar amaçlandığı gibi alarmları "yerleşik müşterilerden" uzaklaştırıyor; ancak bu holdout'ta yerleşik entity alarmları ortalamadan daha az yanlış pozitif içeriyor.

Örneklem koşusu (SAMPLE_N=50000, 10.000 holdout, 228 pozitif; yalnızca duman testi, örneklem holdout hafta sonu ve sezon günü içermediği için C3 ve C7 holdout'ta tetiklenmez): %1'de FP 88 -> 84, recall 0,053 -> 0,070; %5'te FP 468 -> 454, recall 0,140 -> 0,202. Tam veride yön tersine döner; örneklem sonucu genellenemez.

## Ablation - İLK TASARIM (TAM veri, holdout)
"without X" = yalnızca X grubu kapalı; "only X" = yalnızca X açık (sınırlar ve koruma her ikisinde de açık).

| Varyant | PR-AUC | Prec@%1 | Recall@%1 | FP@%1 | Prec@%5 | Recall@%5 | FP@%5 |
|---|---|---|---|---|---|---|---|
| bağlam yok (önce) | 0,081 | 0,158 | 0,046 | 995 | 0,116 | 0,168 | 5.222 |
| tüm kurallar | 0,078 | 0,120 | 0,035 | 1.040 | 0,104 | 0,151 | 5.291 |
| C1'siz | 0,077 | 0,121 | 0,035 | 1.039 | 0,101 | 0,147 | 5.309 |
| C2'siz | 0,079 | 0,131 | 0,038 | 1.027 | 0,104 | 0,151 | 5.291 |
| C3'süz | 0,079 | 0,120 | 0,035 | 1.040 | 0,106 | 0,154 | 5.281 |
| **C4'süz** | **0,098** | **0,161** | **0,047** | **992** | **0,160** | **0,232** | **4.963** |
| C5'siz | 0,078 | 0,122 | 0,035 | 1.038 | 0,104 | 0,151 | 5.291 |
| C6'sız | 0,073 | 0,120 | 0,035 | 1.040 | 0,099 | 0,143 | 5.324 |
| C7'siz | 0,078 | 0,120 | 0,035 | 1.040 | 0,104 | 0,151 | 5.291 |
| C8'siz | 0,079 | 0,127 | 0,037 | 1.032 | 0,106 | 0,155 | 5.278 |
| C9'suz | 0,070 | 0,115 | 0,034 | 1.046 | 0,096 | 0,139 | 5.341 |
| yalnızca C1 | 0,081 | 0,159 | 0,046 | 994 | 0,117 | 0,170 | 5.217 |
| yalnızca C2 | 0,079 | 0,143 | 0,042 | 1.013 | 0,114 | 0,166 | 5.231 |
| yalnızca C3 | 0,076 | 0,139 | 0,040 | 1.018 | 0,100 | 0,145 | 5.318 |
| yalnızca C4 | 0,067 | 0,137 | 0,040 | 1.020 | 0,094 | 0,136 | 5.353 |
| yalnızca C5 | 0,081 | 0,157 | 0,046 | 996 | 0,115 | 0,167 | 5.226 |
| yalnızca C6 | 0,094 | 0,159 | 0,046 | 994 | 0,161 | 0,233 | 4.958 |
| yalnızca C7 | 0,081 | 0,158 | 0,046 | 995 | 0,116 | 0,168 | 5.222 |
| yalnızca C8 | 0,079 | 0,123 | 0,036 | 1.037 | 0,117 | 0,171 | 5.213 |
| yalnızca C9 | 0,096 | 0,157 | 0,046 | 996 | 0,161 | 0,233 | 4.958 |
| koruma G1 yok | 0,077 | 0,124 | 0,036 | 1.035 | 0,097 | 0,141 | 5.335 |
| sınırlar yok | 0,078 | 0,120 | 0,035 | 1.040 | 0,104 | 0,151 | 5.291 |
| sınır ve koruma yok | 0,077 | 0,124 | 0,036 | 1.035 | 0,097 | 0,141 | 5.335 |

Yorum (betimleyici; kurallar bu tabloya göre değiştirilmedi):
- **C4 (trusted entity) en büyük zarar kaynağı.** Tek başına çıkarılınca tüm metrikler bağlamsız skorun üstüne çıkar (%5'te FP 5.222 -> 4.963). Etiketsiz neden: entity = card1 + addr1 bir kart GRUBUDUR (K-05); holdout'ta medyan geçmiş 116 işlem, satırların %77'si `ent_txn_count >= 20` ve C4 satırların %61'inde tetiklenir. "Güvenilir" bir azınlığı değil, çoğunluğu tanımlıyor; ayrıca etiket aynı kart/e-postaya yayıldığı için (varsayım 9) uzun geçmişli gruplar dolandırıcılık geçmişi de taşıyabilir.
- **C6 ve C9 en çok yardım eden gruplar** (yalnızca C6 / yalnızca C9: %5'te FP 4.958, recall 0,233). İkisi de büyük ölçüde aynı satırları (ProductCD = C, addr2 boş) artırır. **Uyarı:** C9'un yönü (C artır, W azalt) EDA'nın etiketli fit tablosuyla örtüşür (C %11,3, W %2,1); değer o tablodan seçilmedi ama bu kuralın holdout başarısı tamamen etiketsiz bir kanıt sayılmamalıdır.
- **C5 etkisi ~0:** Adım 5'teki burst entity'si (card1 15775, addr1 330) holdout'ta 1.416 işlem yapıyor ama `burst_ratio_24h` medyanı ~82 (kendi geçmiş ortalamasının 82 katı): kural tanımı gereği bu bir "gerçek değişim"dir ve C5 tetiklenmez (entity satırlarının yalnızca %1,6'sı). Bu entity'nin birleşik skorun üst %1'inde zaten yalnızca 23 işlemi vardı (sonra 0; diğer indirimler nedeniyle).
- **C7 holdout'ta hiç tetiklenmez** (sezon fit döneminde).
- **Koruma G1** %5 bütçede recall'u 0,141'den 0,151'e çıkarır (FP 5.335 -> 5.291): card testing satırlarının indirimle bastırılmasını engellemek ölçülebilir fayda sağlıyor.
- **Sınırlar** bu holdout'ta sıralamayı değiştirmiyor (aynı metrikler); yalnızca uç çarpanları keser.

## Düzeltme (holdout sonucunda fark edilen sorun; etiketle değil tanım ilkesiyle düzeltildi)

**Fark edilen sorun.** İlk tasarım holdout'ta FP'yi artırdı; ablation sorunu C4'e bağladı. Düzeltme holdout etiketine göre ayar DEĞİLDİR: etiketsiz kapsam tablosu C4'ün "güvenilir" dediği kümenin bir azınlık değil çoğunluk olduğunu gösteriyordu (fit %47,8, holdout %61,1). Tanım ilkesi: "trusted" küçük bir azınlıktır. Bu ilke ve kullanıcının verdiği yeni tanım uygulandı; katsayılar değişmedi.

Yapılan dört değişiklik (kullanıcı talebi):
1. **C4 yeniden tanımlandı** (eşikler config + öğrenilmiş parametre): önceki işlem >= fit q90 (`trusted_min_history`, tam veride 809), entity yaşı >= 30 gün, |amt_zscore_ent| <= 2, bilinen cihaz VE bilinen e-posta (`known_device`, `known_email` ayrı türetilmiş kolonlar).
2. **C6/C9 dışlayıcı grubu:** C6a, C6b, C9a, C9b `exclusive_group: geo_product`; aynı satırda birden fazlası tetiklenirse yalnızca en büyük çarpan uygulanır (eşitlikte config sırasındaki ilk kural; C6b ile C9a ikisi de x1,10 olduğundan C6b kalır). Böylece C satırlarındaki x1,21 çift sayım kalktı. Revize koşuda C9a yalnızca C6b'nin tetiklenmediği C satırlarında görünür (holdout %0,9).
3. **Öğrenilmiş parametreler** `artifacts/context/` altına taşındı (`paths.params_dir: artifacts/context`); eski `reports/context/context_params.json` silindi.
4. **Sıralama kırpılmamış skorla:** `adjusted_score_unclipped = raw_score x toplam` alarm bütçesi ve tüm metriklerde kullanılır; `adjusted_score` [0,1]'e kırpılmış haliyle yalnızca çıktı/gösterim içindir. `adjust_one` aynı değeri açıklamadaki `total` kaydında döner; batch = tek kayıt testi bu kolonu da karşılaştırır.

### C4 kapsaması (etiketsiz, `reports/context/c4_coverage.csv`)
| Koşul | Fit payı | Holdout payı |
|---|---|---|
| `ent_txn_count >= 809` (fit q90) | %10,0 | %20,5 |
| `ent_age_days >= 30` | %64,6 | %95,4 |
| `abs_amt_zscore_ent <= 2` | %92,9 | %94,2 |
| `known_device = 1` | %13,2 | %12,4 |
| `known_email = 1` | %69,6 | %75,3 |
| **hepsi birlikte (C4)** | **%2,0** | **%4,0** |

**Hedef %10-15'in altında; olduğu gibi raporlanıyor.** Bağlayıcı koşul `known_device`: cihaz bilgisi yalnızca identity kaydı olan işlemlerde var (fit satırlarının %13,2'sinde bilinen cihaz). Etiketsiz tek ayar kolu q seviyesidir; fit kapsamına bakarak (etiketsiz) denendi: q = 0,85 -> %2,6, 0,80 -> %3,0, 0,75 -> %3,3. Makul bir q seviyesi %10'a ulaşmadığı için q = 0,90 (tasarımdaki değer) korundu. Holdout'ta kapsamın iki katına çıkması ömür boyu sayaçların zamanla büyümesinden kaynaklanır (K-18); eşik fit'te sabitlendiği için holdout'ta daha çok entity eşiği aşar.

Örneklem (SAMPLE_N=50000): q90 = 51; örneklem ~2 hafta olduğu için `ent_age_days >= 30` hiç sağlanmaz ve C4 tetiklenmez (fit ve holdout %0). Yalnızca duman testidir.

### Önce / sonra: üç satır (TAM veri, holdout, `reports/context/fp_comparison.csv`)
| Bütçe | Skor | Alarm | FP | Precision | Recall | PR-AUC |
|---|---|---|---|---|---|---|
| %1 | Adım 5 (`anomaly_score_norm`) | 1.182 | 995 | 0,158 | 0,046 | 0,081 |
| %1 | ilk tasarım (kırpılmış sıralama + ham eşitlik kırıcı) | 1.182 | 1.040 | 0,120 | 0,035 | 0,078 |
| %1 | **revize tasarım** | 1.182 | **983** | **0,168** | **0,049** | **0,094** |
| %5 | Adım 5 | 5.906 | 5.222 | 0,116 | 0,168 | 0,081 |
| %5 | ilk tasarım | 5.906 | 5.291 | 0,104 | 0,151 | 0,078 |
| %5 | **revize tasarım** | 5.906 | **5.068** | **0,142** | **0,206** | **0,094** |

Revize tasarım Adım 5'e göre FP'yi %1'de 12 (-%1,2), %5'te 154 (-%2,9) azaltır; recall %1'de 0,046 -> 0,049, %5'te 0,168 -> 0,206. ROC-AUC 0,683 -> 0,686. İlk tasarımın sayıları `reports/context/initial_design/fp_impact.csv` dosyasından okunur (korunmuş sonuç; yeniden hesaplanmadı).

Kaynak ayrımı (betimleyici): revize tasarımı kırpılmış skor + ham eşitlik kırıcı ile sıralamak %1'de FP 958, %5'te 5.068 verir. Yani iyileşme kırpılmamış sıralamadan değil, C4 ve dışlayıcı gruptan gelir; %1'de kırpılmış sıralama biraz daha iyi görünür. Kullanıcı kararı gereği kırpılmamış sıralama kullanılır (sıralama bilgisi 1,0'da kaybolmaz).

Ölçek uyarısı: FP azalması küçüktür ve tek holdout'tadır; güven aralığı hesaplanmadı.

Etiketsiz alarm profili (revize): %1'de uzun geçmişli (`>= 20`) alarmlar 920 -> 719, ilk görülen 28 -> 102; %5'te 4.778 -> 4.207 ve 98 -> 381.

### 1,0'da yığılma ve kesimde eşitlik (holdout)
| | Adım 5 | İlk tasarım | Revize tasarım |
|---|---|---|---|
| Kırpılmış skoru = 1,0 olan satır | 25 | 2.006 | 2.682 |
| Sıralama skoru | `anomaly_score_norm` | `adjusted_score` (kırpılmış) | `adjusted_score_unclipped` |
| %1 kesiminde aynı skoru paylaşan satır | 1 | 2.006 (kesim 1,0 yığınının içinde) | 1 |
| %5 kesiminde aynı skoru paylaşan satır | 1 | ölçülmedi (ilk tasarımın satır skorları saklanmamıştı; kesim 1,0'ın altında) | 1 |

Kırpılmamış sıralamada kesimlerde eşitlik yok (1 = yalnızca kesimdeki satırın kendisi). Revize tasarımda kırpılmış 1,0 sayısı arttı çünkü C4 indirimi artık az satıra uygulanıyor; bu yalnızca gösterimi etkiler.

### Ablation - REVİZE TASARIM (TAM veri, holdout, `reports/context/ablation.csv`)
| Varyant | PR-AUC | Prec@%1 | Recall@%1 | FP@%1 | Prec@%5 | Recall@%5 | FP@%5 |
|---|---|---|---|---|---|---|---|
| bağlam yok (Adım 5) | 0,081 | 0,158 | 0,046 | 995 | 0,116 | 0,168 | 5.222 |
| tüm kurallar (revize) | 0,094 | 0,168 | 0,049 | 983 | 0,142 | 0,206 | 5.068 |
| C1'siz | 0,095 | 0,180 | 0,052 | 969 | 0,146 | 0,212 | 5.044 |
| C2'siz | 0,098 | 0,183 | 0,053 | 966 | 0,144 | 0,209 | 5.055 |
| C3'süz | 0,097 | 0,206 | 0,060 | 939 | 0,144 | 0,209 | 5.057 |
| C4'süz | 0,098 | 0,166 | 0,048 | 986 | 0,148 | 0,216 | 5.030 |
| C5'siz | 0,094 | 0,169 | 0,049 | 982 | 0,142 | 0,207 | 5.066 |
| C6'sız | 0,092 | 0,161 | 0,047 | 992 | 0,143 | 0,207 | 5.064 |
| C7'siz | 0,094 | 0,168 | 0,049 | 983 | 0,142 | 0,206 | 5.068 |
| C8'siz | 0,091 | 0,164 | 0,048 | 988 | 0,142 | 0,207 | 5.065 |
| C9'suz | 0,086 | 0,148 | 0,043 | 1.007 | 0,133 | 0,194 | 5.118 |
| koruma G1 yok | 0,093 | 0,168 | 0,049 | 983 | 0,141 | 0,205 | 5.072 |
| sınırlar yok | 0,094 | 0,168 | 0,049 | 983 | 0,142 | 0,206 | 5.068 |
| sınır ve koruma yok | 0,093 | 0,168 | 0,049 | 983 | 0,141 | 0,205 | 5.072 |

"Yalnızca X" satırları da dosyadadır. Yorum (betimleyici; kurallar bu tabloya göre değiştirilmedi):
- C4 artık zarar kaynağı değil: %1'de hafif yardım (çıkarınca FP 983 -> 986), %5'te hafif zarar (5.068 -> 5.030). Etkisi küçük, çünkü yalnızca holdout'un %4'üne dokunuyor.
- En çok yardım eden C9 (çıkarınca %5'te FP +50); yönü fit EDA etiket tablosuyla uyumlu olduğu için bu katkı tamamen etiketsiz kanıt sayılmamalı.
- C3, C1 ve C2 çıkarıldığında metrikler iyileşiyor (en belirgin C3: %1'de FP 983 -> 939). Bunlar sonraki karar adayları; etiketle ayar yasağı nedeniyle bu adımda değiştirilmedi.
- C5 ve C7 etkisiz (nedenler ilk tasarım bölümünde); koruma %5'te küçük fayda (5.072 -> 5.068); sınırlar sıralamayı değiştirmiyor.

### Düzeltmede eklenen testler
C4'ün her koşulunun tek tek gerekli olması (yalnızca e-posta / yalnızca cihaz / eşik altı geçmiş / 30 günden genç), C6/C9 dışlayıcı grubu (eşit çarpanda ilk kural, büyük çarpan kazanır, tek kural korunur), kırpılmamış skorun 1'i aşabilmesi ve `raw x total` eşitliği, batch = tek kayıt eşitliğinde kırpılmamış skor, `trusted_min_history` öğrenimi.

## Tasarımdan sapmalar ve uyarlamalar
1. **C5 yalnızca skoru düşürdüğünde uygulanır** (`only_if_lowers: true`). Ağırlığı yarıya indirmek, temporal skoru diğer katmanların altındaysa toplamı YÜKSELTİR; amaç burst'ü sönümlemek olduğu için bu durumda kural uygulanmaz. Ayrıca C5 tek başına toplam sınırların dışına çıkamaz (çarpanı [0,5; 1,5]'e kırpılır; kuantil tablosu düşük skorlarda oranı 0'a yaklaştırabiliyordu).
2. **C5'te "sık işlem yapan" tanımı** eklendi: `ent_daily_avg >= 1` (günde en az bir işlem) ve `ent_txn_count >= 5` (C3 ile aynı "yerleşik" eşiği). Tasarım bu iki eşiği belirtmiyordu; iş mantığıyla seçildi, config'te.
3. **"Bilinen cihaz/email"** fit kümesinden statik bir liste değil, entity'nin işlemden ÖNCEKİ geçmişidir (`device_ent_match >= 1` veya `email_ent_known`). Sızıntı açısından eşdeğerdir (yalnızca geçmiş), entity bazlı anlam taşır ve Adım 3'ün geçmiş feature'larıyla aynı tanımı kullanır. `email_ent_known` features.parquet'te olmadığı için `src/context/inputs.py` hesaplar.
4. **C1'de hafta içi** `is_weekend` (referans takvim) ile ölçülür, `is_business_hours`'taki yerel takvim değil; böylece C1 ve C3 birbirini dışlar. Fark satırların ~%6,3'ünü etkiler (varsayım 4).
5. **C7 "hacim/velocity kaynaklı"** = temporal katman en büyük ağırlıklı katkı (`dominant_layer`).
6. **Eşitlik kırma** (değerlendirme): yukarıda; tasarımda yoktu, 1,0'da doyma nedeniyle eklendi.
7. **Öğrenilen parametrelerin yeri:** ilk koşuda `reports/context/` altındaydı (yazma alanı nedeniyle); düzeltmede kullanıcı izniyle `artifacts/context/`'e taşındı (`paths.params_dir`), eski dosya silindi.

## Bilinen sınırlar
- Holdout'ta FP artıyor (yukarıda); C4 eşiği kart-grubu entity proxy'si için fazla geniş. Kurallar etiketle ayarlanmadı; değişiklik kullanıcı kararıdır.
- C6b ile C9a çoğunlukla aynı satırları artırır (çift sayım, fiilen x1,21).
- 1,0'da doyma: 2.006 holdout satırı; üst dilim içinde sıra yalnızca eşitlik kırıcıdan gelir.
- C7 holdout'ta ölçülemez (sezon fit'te); C5 Adım 5'teki burst entity'sini hedeflediği halde onu yakalamaz (burst kendi geçmişine göre gerçek bir değişim).
- Saat dilimi, hafta sonu, addr2 = ABD, 3 ondalık = kur çevrimi ve D1 = kart yaşı varsayımdır (docs/assumptions.md 1-7); C1, C2, C3, C6, C8 bunlara bağlıdır.
- Online yolda kayıt şu alanları taşımalıdır: yukarıdaki girdi kolonları + `email_ent_known` + dört katman skoru; eksik kolon `KeyError` verir (sessizce yanlış tetiklenme olmasın diye).
- `scripts/run_pipeline.py` içindeki context adımı hâlâ `scripts/adjust_context.py`'yi gösterir; bu adımın yazma alanı dışında olduğu için bağlanmadı (aşağıda).

## Testler (tests/context, ilk tasarımda 30, düzeltme sonrası 38 test)
Her kural için tetiklenen/tetiklenmeyen durum (C1-C4, C6a, C6b, C8, C9a, C9b parametreli; C5 burst ve düşük temporal; C7 baskın katman), nötr kayıt değişmez, koruma skoru ham skorda tutar ama artışı engellemez, üst/alt sınır ve [0,1] kırpma, **batch = tek kayıt** (300 rastgele satır, skor ve uygulanan kural listesi eşit; her kural en az bir kez tetiklenir), çıktı şeması ve açıklama alanları, eksik girdi kolonu hatası, config doğrulama (yinelenen id, bilinmeyen kolon), en az 6 gerekçeli kural, NaN karşılaştırması, parametre fit + JSON gidiş-dönüş, `email_ent_known`'un yalnızca önceki satırları kullanması, eşitlik kırıcı, ablation varyant sayısı, `src/context`'te `isFraud` geçmemesi, container provider'ı.

## Komutlar
Örneklem: `SAMPLE_N=50000 python scripts/run_context.py` (~2 sn). Tam veri: `python scripts/run_context.py` (~16 sn; önce `make score`). `--no-eval` değerlendirmeyi atlar.

## Bir sonraki adımın girdisi (Adım 7)
Rule engine `reports/scores/adjusted_score.parquet` içindeki skoru okur: gösterim/çıktı için `adjusted_score` ([0,1]), sıralama ve alarm bütçesi için `adjusted_score_unclipped`; açıklama için `applied_adjustments`, denetim için `raw_score` ve `raw_anomaly_score`. Eşitlik kalırsa `raw_anomaly_score` ikincil anahtardır. Online yol: `Container.context_adjuster.adjust_one(record, anomaly_score_norm) -> AdjustedResult`. Kural engine'i card testing gibi kritik sinyalleri ayrıca değerlendirmelidir; context katmanı yalnızca onların indirimle bastırılmasını engeller.
