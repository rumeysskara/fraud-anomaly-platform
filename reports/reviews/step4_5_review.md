# Adım 4-5 İnceleme Raporu (anomali katmanları, normalizasyon, birleştirme)

Denetçi: step-review. Kod değiştirilmedi, commit yapılmadı. Geçici analiz betikleri scratchpad dizininde çalıştırıldı, repoya dosya eklenmedi.

**SONUÇ: GEÇTİ (küçük/önemli notlarla). Kritik bulgu yok.** Commit'e hazır; önemli bulgular dokümana not düşülerek veya kullanıcı kararıyla kapatılabilir (aşağıda).

## 1. Kontrol tablosu

| # | Kontrol | Durum | Kanıt |
|---|---|---|---|
| 1 | `make test` | ✅ | `112 passed in 14.31s` |
| 2 | `make lint` (ruff + black) | ✅ | `All checks passed!`, `93 files would be left unchanged` |
| 3 | isFraud sızıntısı | ✅ | `grep -rn isFraud src scripts configs`: `src/detection` ve `src/scoring` içinde yok. Kalan eşleşmeler: `src/profiling/entity.py:1` (Adım 1-2'den kalan docstring, "never read"), `configs/settings.yaml:14` (`label_column`, Adım 0), `configs/weights.yaml:2` (yorum). Hiçbiri etiketi okumaz. Etiket yalnızca `scripts/run_scoring.py:evaluate_holdout` içinde `load_data()` ile okunur; `tests/scoring/test_no_label_use.py` bunu kilitliyor |
| 4 | Fit/score ayrımı | ✅ | `ScoringService.fit(df.loc[fit_idx])` (run_scoring.py); `fit` içinde yalnızca `fit_df`; normalizer ve toplam normalizer fit skorlarından; B ağırlıkları fit'ten; test `test_fit_uses_only_the_fit_rows` |
| 5 | Zaman bazlı split | ✅ | `split_by_time` (loader) kullanılıyor; tam veri fit 472.432 / holdout 118.108 (%80/%20); rastgele split yok |
| 6 | Zamansal sızıntı | ✅ | Entity-saat geçmişi `groupby.cumcount()` (yalnızca önceki satırlar); testler: `test_hour_history_is_past_only_and_shrinks`, `test_future_rows_do_not_change_past_temporal_scores`; ilk işlem: entity `w=0`, `test_entity_shrinkage_weight_and_first_transaction` |
| 7 | Ağırlıklar config'te, toplam 1 | ✅ | `configs/weights.yaml` 0,35/0,25/0,20/0,20; `load_weights` toplamı doğruluyor |
| 8 | Config'te hardcode | ⚠️ | Parametreler config'te. Kodda sabit kalanlar: kolon adları (`amt_log`, `ent_std_amt`, `hour`, `day_of_week`...), `RATIO_FLOOR`, `-1.0` sentinel değeri. Küçük |
| 9 | Dosya alanı | ⚠️ | `scripts/run_pipeline.py` (tek satır: `score_anomalies.py` -> `run_scoring.py`) anomaly-engineer alanı dışında; mantıklı ve gerekli düzeltme ama kayıt altına alınmalı. `docs/step4.md` + `docs/step5.md` (ajan tanımı `docs/step4-5.md` diyor), kullanıcı tercihi olabilir |
| 10 | `interfaces.py` / `container.py` yalnızca ekleme | ✅ | `git diff`: interfaces.py +12 satır (`Normalizer`), container.py +4 satır (`scoring_service` Singleton `ScoringService.load`); silinen satır yok |
| 11 | Sözleşme | ✅ | 4 katman `Detector` (LayerDetector), `WeightedAverage` `Aggregator`, `QuantileNormalizer` `Normalizer`; Factory (`build_detector`); container testi var |
| 12 | docs/step4.md, step5.md | ✅ | Girdi, çıktı + şema, sonraki girdi, sınırlar, "isFraud kullanıldı mı: hayır" notları var; tablo sayıları `holdout_metrics.csv` / `ablation.csv` ile eşleşti |
| 13 | docs/decisions.md K-11..K-19 | ✅ | Aşağıda 2. bölüm |
| 14 | README notu | ✅ | README.md:6 "Geliştirmede Claude Code kullanılmıştır..." |
| 15 | Kişisel çalışma notları | ✅ | kişisel çalışma notları .gitignore'da (repo dışı) |
| 16 | Örneklem -> tam veri | ✅/⚠️ | Tam veri çıktıları mevcut (`reports/scores/*`, `artifacts/detectors/*`). Doküman "~90 sn, ~3 GB" diyor: yeniden koşturulmadı (repo çıktılarını ezmemek için), doğrulanmadı |
| 17 | Batch = online | ⚠️ | Aşağıda önemli bulgu Ö-2 |

Case maddeleri (Adım 4: column, multivariate, entity, temporal, skorlar ayrı; Adım 5: normalize, weighted aggregation, final raw score, gerekçe): ✅ hepsi karşılanıyor. Skill kontrol listesi: 4 katman [0,1] ✅, ayrı kayıt ✅, config + toplam=1 ✅, `contrib_*` ✅, aggregation gerekçesi ✅ (step5.md + K-17), katman testleri (fit/score/explain) ✅, doküman ✅.

## 2. Karar kayıtları / kullanıcı kararlarıyla uyum

| Karar | Kontrol | Sonuç |
|---|---|---|
| K-18 (düzeltilmiş) | `configs/anomaly.yaml`: `drop_always` = day_index, card_start_day; `drop_cumulative` = ent_txn_count, ent_avg_amt, ent_max_amt, ent_std_amt, ent_age_days, ent_unique_device, ent_unique_email, device_ent_match. `reports/scores/mv_input.csv` içinde `ent_cnt_1h/6h/24h/7d`, `ent_sum_1h/6h/24h/7d` VAR; dışlananların hiçbiri YOK | ✅ uyumlu. Eski karar metni silinmeden üstü çizili, düzeltme notu var |
| ent_txn_count yalnızca geri çekme ağırlığında | `grep ent_txn_count src/detection`: yalnızca `entity.py` (`count_column`, `w`) | ✅ |
| Ağırlıklar 0,35/0,25/0,20/0,20 | weights.yaml, K-17, step5.md | ✅ |
| column 28 kolon, V yok | yaml `column.columns` 28 kolon, V yok | ✅ |
| IF-core ana, IF-full yalnızca ablation | `ScoringService` yalnızca `build_all` (core); IF-full yalnızca `run_scoring.py` ablation'ında | ✅ |
| IF-core girdi sayısı | K-13 "75 + 15 = 90": `mv_input.csv` 90 satır (75 değer + 15 `__na`) | ✅ (IF-full "460" doğrulanmadı, joblib'i kaydedilmiyor) |
| Ağırlıklar/IF-core holdout'a göre değiştirilmez | step5.md "DEĞİŞTİRİLMEDİ", K-17; ablation yalnızca rapor | ✅ |
| K-19 | step5.md "Bir sonraki adımın girdisi" `anomaly_score_norm` | ✅ |

Sapma yok. (Not: K-18'de `ent_avg_amt`/`ent_std_amt` "kümülatif" listesinde; bunlar büyüyen değil çalışan ortalama olduğundan sentetik sürüklenme testinde sürüklenmiyor. Kullanıcı kararı gereği listede kalıyor, entity katmanı yine kullanıyor; sorun değil, yalnızca terminoloji notu.)

## 3. Bulgular

### Kritik
Yok.

### Önemli
- **Ö-1 Temporal üst %1 tek bir entity (ayrıntı: Ek Görev 1).** Holdout temporal en yüksek %1 (1.181 işlem) içinde 1.138'i (%96,4) tek entity'den (`card1=15775, addr1=330`, ProductCD S). Skor velocity alt skorunun fit aralığı dışında doymasından geliyor. Bu bir kod hatası değil, yöntemin sınırı. step5.md "review raporunda incelenir" diyor; sonucu dokümana (step5.md "Bilinen sınırlar" veya teknik doküman) yazmak gerekir. Düzeltme/yöntem değişikliği kullanıcı kararıdır (ağırlıklar dokunulmaz kararıyla çelişmez; seçenekler Ek Görev 1 sonunda).
- **Ö-2 Online temporal skor, saklı `HourStore` geçmiş satırı da içerdiğinde batch ile eşleşmiyor.** `run_scoring.py` `service.build_hour_store(df)` ile fit+holdout dahil TÜM satırlardan store kuruyor (artifact). Tam veri artifact'ı yükleyip son 300 satırdan 20'sini `score_one` ile, 3000 satırlık `score_batch` ile karşılaştırdım: multivariate/entity/column farkı 0,0; temporal farkı maks 0,159 (ort. 0,066), `anomaly_score_norm` farkı maks 0,050 (ort. 0,018). Sebep: store, o satırın kendisini ve sonrasını zaten sayıyor (geçmiş satırın yeniden oynatılması). Yeni bir işlem için (store'daki son satırdan sonra) eşitlik geçerli ve testle kanıtlı (`test_temporal_online_equals_batch_with_store`, store öncül satırlardan kuruluyor). step4.md "Batch = online" bölümü bu sınırı belirtmiyor. Öneri: dokümana "geçmişte zaten işlenmiş bir işlemi API'den tekrar oynatmak batch skorunu birebir vermez" notu; Adım 9-10'da geçmiş-işlem yeniden skorlaması (örn. /score ile holdout satırı) beklenirse karar gerekir.

### Küçük
- K-1 Kod içinde sabit kolon adı ve değerler (`RATIO_FLOOR=1e-6`, `-1.0` sentinel, `amt_log`, `hour`, `day_of_week`, `is_low_volume_window`...). Config'e taşınabilir.
- K-2 `scripts/run_pipeline.py` değişikliği alan dışı (gerekli tek satır; sonraki adımlarda platform-architect alanı olarak bilinsin). `docs/step4.md`/`step5.md` adlandırması ajan tanımından (`step4-5.md`) farklı.
- K-3 `RobustPreprocessor.fit` idempotent değil: `na_cols`/`log_cols` sıfırlanmıyor, aynı nesne ikinci kez fit edilirse liste çoğalır (şu an her zaman yeni nesne fit ediliyor; tetiklenmiyor).
- K-4 Artifact boyutları: `column.joblib` 97 MB (28 kolon x 472k sıralı fit dizisi), `temporal.joblib` 36 MB; API yükleme süresine etkili olabilir (kuantil özetiyle küçültülebilir). Artifacts gitignore'da.
- K-5 Fit→holdout sürüklenmesi (IF-core girişinde, kümülatif olmayan): `os_browser_rare` (+0,76 std), `ent_cnt_1h` (+0,68, Ö-1'deki entity'nin patlaması), `holiday_season` (-0,33, fit'te öğrenilen sezon), `avg_inter_arrival` (+0,33), D14/D11/D15/D10 (0,15-0,23). Kümülatif değil, K-18 kapsamı dışında; bilgi amaçlı.
- K-6 Sayısal süre/bellek iddiaları (~90 sn, ~3 GB) ve IF-full 460 girdi sayısı yeniden üretilmedi.

## 4. Ek Görev 1 - Temporal üst %1 profili (etiket kullanılmadı)

Kaynak: `reports/scores/layer_scores.parquet` (tam veri), `data/processed/features.parquet`, `merged.parquet` (ProductCD). Holdout 118.108 satır; üst %1 = ham temporal skora göre en yüksek 1.181 satır (normalize skorda bağ yok, eşik 0,9992). Alt skorlar kayıtlı `temporal.joblib` ile yeniden hesaplandı (salt okunur).

| Ölçü | Üst %1 | Tüm holdout |
|---|---|---|
| Farklı entity (card1+addr1) | **34** (1.181 işlemde) | - |
| En büyük entity payı | **1.138 işlem = %96,4** (`15775\|330`) | bu entity holdout'un %1,2'si (1.416 satır) |
| İlk 5 entity payı | %97,5 | - |
| Entity büyüklüğü (tüm veride işlem sayısı) medyan / ort. / maks | 1.453 / 1.435 / 9.928 (min 14) | medyan 132, p75 720, p90 2.290, p99 9.928 |
| `ent_txn_count` p10 / p25 / p50 / p75 / p90 / p99 | 259 / 461 / 821 / 1.134 / 1.315 / 1.424 | 5 / 23 / 116 / 628 / 1.985 / 8.746 |
| `is_first_seen` oranı | **0,0** | 0,029 |
| Tek-işlemlik entity | 0,0 | 0,022 |
| ProductCD | **S %96,5**, W %2,8, C %0,5, H %0,1, R %0,1 | W %79,3, C %10,3, R %4,7, H %2,8, **S %3,0** |
| has_device | %86,7 | %16,2 |

Entity-düzeyi ayrıntı (`15775|330`): toplam 1.453 işlem, yalnızca 37'si fit'te, 1.416'sı holdout'ta; holdout satırlarının %99,9'u ProductCD S; 1.138/1.416'sı (%80) üst %1'de. Medyan `ent_cnt_1h` = 66 (fit p99.9 = 12), medyan `ent_cnt_24h` = 282 (fit p99.9 = 138), medyan `ent_sum_1h` = 7.116 USD (fit p99.9 = 2.982), medyan `time_since_last_txn` = 12 sn (holdout medyanı 42.415 sn). Holdout'taki tüm S işlemlerinin (3.501) 1.140'ı (%33) üst %1'de.

Baskın alt skor (ortalama alt skor, üst %1 / tüm holdout):

| Alt skor | Üst %1 | Holdout | Ağırlıklı katkı payı (üst %1) |
|---|---|---|---|
| velocity | **5,50** | 0,50 | **%64,6** |
| inter_arrival | 2,57 | 0,53 | %30,2 |
| hour_rarity | 0,27 | 0,45 | %3,2 |
| low_volume_window | 0,08 | 0,09 | %1,0 |
| baseline_volume | 0,09 | 0,07 | %1,0 |

Satırların %97,1'inde baskın (ağırlıklı en büyük) alt skor velocity, %1,8 inter_arrival, %1,1 hour_rarity. Tüm holdout'ta baskın alt skor dağılımı hour_rarity %44,6 / inter_arrival %28,4 / velocity %24,8. Velocity ortalaması 5,50, teorik tavana (`-log10(1/(472.432+1))` = 5,67) yakın: yani doymuş.

`ent_txn_count` kovalarında ortalama temporal (normalize) skor / üst %1'e düşme oranı: 0 -> 0,16 / %0; 1-4 -> 0,40 / %0; 5-19 -> 0,45 / %0,03; 20-99 -> 0,42 / %0,01; 100+ -> 0,59 / %1,88. Spearman(ham temporal, ent_txn_count) = 0,42 (velocity alt skoru: 0,68; hour_rarity ve low_volume ~0).

**Yorum.** Üst %1, "çok sayıda farklı sıra dışı işlem" değil, tek bir yüksek hacimli entity'nin (card1+addr1, neredeyse tamamen ProductCD S) fit dönemine hiç benzemeyen bir burst'ü: fit'te yalnızca 37 işlemi var, holdout'ta dakikada çoklu işlem yapıyor, dolayısıyla fit ECDF kuyruğunun dışında velocity doyuyor. Skor mantıksal olarak "doğru" (fit'e göre aşırı velocity) ama (a) tek entity tüm üst dilimi doldurduğu için katman sıradan bir topluluk/toplayıcı hesabı (card1+addr1 proxy'si çok sayıda gerçek kart/müşteriyi tek anahtarda birleştirmiş olabilir; ProductCD S bu sayıdadır) öne çıkarıyor, (b) skor ent_txn_count ile yüksek korelasyonlu (hacmi yüksek entity = yüksek velocity), (c) top-%1 dilimi pratik olarak tek davranışı ölçüyor. Etiketsiz bu bulgu recall@%1=0,001 sonucunu açıklayan olası nedenle uyumlu (dilim tek bir entity'ye ayrılmış), ama etiketle doğrulama bilerek yapılmadı. Kullanıcının seçebileceği seçenekler (yöntem değişikliği değil sınır kaydı varsayılan): (1) olduğu gibi bırakıp sınırı step5.md'ye yazmak (öneri: ağırlık dokunulmaz kararıyla uyumlu, Adım 6'da `contrib_temporal` incelenir); (2) velocity alt skorunu entity başına tavanlamak / entity'nin kendi velocity geçmişine göre (z) normalleştirmek (yöntem kararı, etiket gerekmez); (3) Adım 6 context katmanında "yüksek hacimli/güvenilir entity" kuralıyla sönümlemek (Adım 6 kapsamıyla doğal uyumlu).

## 5. Ek Görev 2 - Kümülatif kolon listesi testi (taslak, repoya EKLENMEDİ)

**Yöntem.** Kataloğun açıklama/ad kalıbı kırılgan (ör. "Past transaction count..." ile "Past transaction count in the last 1h" aynı kalıpta başlıyor). Daha sağlam yol davranışsal: gerçek feature hattını (`FeaturePipeline`, sentetik veri) SABİT bir akışta (aynı entity'ler, sabit hız, 60 gün) çalıştır; hiçbir şey sürüklenmemeli, yalnızca ömür boyu kümülatif kolonlar ilk yarı -> ikinci yarı ortalamasında büyür. Sürüklenen `model_input` kolonları, `drop_always + drop_cumulative` içinde olmalı. Gerçek veriye bağlı değil.

Taslağı sentetik veride çalıştırdım: sürüklenenler tam olarak `card_start_day, day_index, device_ent_match, ent_age_days, ent_max_amt, ent_txn_count, ent_unique_device, ent_unique_email`; `drop` listesi bunları kapsıyor (uncovered = boş). Pencereli `ent_cnt_*`/`ent_sum_*` sürüklenmiyor (eşik 0,5 std altı). `ent_avg_amt`/`ent_std_amt` sürüklenmiyor (listede olmalarına zarar yok, bu yüzden test yalnızca "sürüklenen ⊆ drop" yönünü doğruluyor). Gerçek veride aynı hesabın en çok sürüklenenleri de bu kolonlardır (day_index 2,3 std, ent_age_days 2,1, card_start_day 0,5, ent_txn_count 0,49, ent_max_amt 0,41, ent_unique_email 0,36).

Dosya önerisi `tests/detection/test_cumulative_drop.py`:

```python
"""drop_cumulative must cover every lifetime-cumulative feature (synthetic stream, no real data)."""

import numpy as np
import pandas as pd

from src.detection.config import load_anomaly_config
from src.features import FeaturePipeline

DAY = 86400
SHIFT_LIMIT = 0.5  # |mean(2nd half) - mean(1st half)| / std(1st half), in first-half stds
N_ROWS, N_DAYS, N_ENTITIES = 6000, 60, 20


def stationary_stream(seed: int = 42) -> pd.DataFrame:
    """Same entities, same behaviour, constant rate: only lifetime-cumulative features can drift."""
    rng = np.random.default_rng(seed)
    n = N_ROWS
    df = pd.DataFrame(
        {
            "TransactionDT": np.sort(rng.integers(0, N_DAYS * DAY, n)),
            "TransactionAmt": np.round(rng.lognormal(3.5, 1.0, n), 2).astype("float32"),
            "ProductCD": rng.choice(["W", "C", "H"], n),
            "card1": rng.integers(1000, 1000 + N_ENTITIES, n),
            "card4": rng.choice(["visa", "mastercard"], n),
            "card6": rng.choice(["debit", "credit"], n),
            "addr1": rng.choice([10.0, 20.0], n),
            "addr2": np.full(n, 87.0),
            "dist1": rng.choice([5.0, 120.0], n).astype("float32"),
            "P_emaildomain": rng.choice([f"mail{i}.com" for i in range(40)], n),
            "R_emaildomain": rng.choice(["gmail.com", None], n),
            "DeviceInfo": rng.choice([f"dev{i}" for i in range(60)], n),
            "id_30": rng.choice(["Windows 10", "iOS 11"], n),
            "id_31": rng.choice(["chrome 63", "safari"], n),
            "id_33": rng.choice(["1920x1080", None], n),
            "D1": rng.choice([0.0, 5.0, 30.0], n).astype("float32"),
            "C1": rng.integers(0, 5, n).astype("float32"),
            "V1": rng.normal(size=n).astype("float32"),
        }
    )
    df["has_identity"] = df["DeviceInfo"].notna()
    df.index = pd.RangeIndex(1, n + 1, name="TransactionID")
    return df


def drifting(features: pd.DataFrame, columns: list[str]) -> set[str]:
    """Columns whose mean moves more than SHIFT_LIMIT first-half stds between the halves."""
    half = len(features) // 2
    out = set()
    for col in columns:
        x = features[col].astype("float64")
        first, second = x.iloc[:half], x.iloc[half:]
        if first.std() > 0 and abs(second.mean() - first.mean()) / first.std() > SHIFT_LIMIT:
            out.add(col)
    return out


def test_drop_lists_cover_every_drifting_model_input():
    common = load_anomaly_config()["common"]
    dropped = set(common["drop_always"]) | set(common["drop_cumulative"])
    frame = stationary_stream()
    pipe = FeaturePipeline.from_config().fit(frame, clusters=None)  # fit on all: no fit/holdout artefact
    feats = pipe.transform(frame)
    cols = [
        c for c in pipe.model_input_columns
        if not c.startswith("V") and pd.api.types.is_numeric_dtype(feats[c])
    ]
    uncovered = drifting(feats, cols) - dropped
    assert not uncovered, f"drifts like a lifetime-cumulative column but is not dropped: {sorted(uncovered)}"


def test_drop_columns_are_real_features():
    """A typo in the config would silently drop nothing."""
    common = load_anomaly_config()["common"]
    frame = stationary_stream()
    pipe = FeaturePipeline.from_config().fit(frame, clusters=None)
    names = set(pipe.catalog["name"])
    assert (set(common["drop_always"]) | set(common["drop_cumulative"])) <= names
```

Notlar: (1) `FeaturePipeline.fit` tüm akış üzerinde çağrıldı; yalnızca fit-bağımlı `amt_fit_freq` gibi kolonların fit/holdout artefaktı yaratmaması için (80/20 fit ile -0,50 std sahte sürüklenme verdi). (2) Test yalnızca "sürüklenen ⊆ drop" yönünü doğrular; yeni bir kümülatif feature eklenirse test kırılır ve kullanıcıyı K-18 listesini güncellemeye zorlar. (3) Taslak yukarıdaki sentetik koşuda doğrulandı (scratchpad); repoya `make test`/`make lint` ile eklenirken black formatlamasını çalıştırın.

## 6. Düzeltilmesi gerekenler (kısa liste)
1. (Önemli) step5.md/teknik dokümana Ö-1 bulgusunu (tek entity, doymuş velocity) yaz; yöntem kararı kullanıcıdan (Ek Görev 1 sonu, seçenek 1-3).
2. (Önemli) step4.md "Batch = online" bölümüne Ö-2 sınırını yaz (store tüm satırları içeriyor, geçmiş satırı yeniden oynatma batch'ten sapar).
3. (Küçük) K-1..K-4 isteğe bağlı; Ek Görev 2 testini eklemeyi kullanıcıya sor.

## 7. Kullanıcının karar vermesi gerekenler
- Temporal velocity alt skorunun tek-entity doygunluğu için: sınır olarak kaydet / velocity'yi entity başına normalleştir / Adım 6'da context ile sönümle.
- Tarihsel işlem yeniden skorlamasının (online) batch ile birebir olması beklenecek mi? (Evet ise HourStore yalnızca fit dönemi veya "o ana kadar" mantığıyla kurulmalı.)
- `test_cumulative_drop.py` taslağı repoya eklensin mi?
