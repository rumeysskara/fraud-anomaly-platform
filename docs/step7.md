# Adım 7 - Configurable Rule Engine

**isFraud kullanıldı mı: hayır - yalnızca evaluation'da raporlama.** Kural koşulları, eşikler, risk artışları ve öncelikler etiketle seçilmedi. Eşikler fit kümesinin (TransactionDT'ye göre ilk %80) yüzdelikleridir. `src/rules/` ve `configs/rules*.{yaml,json}` içinde `isFraud` geçmez (testle kontrol edilir). Etiket yalnızca `scripts/run_rules.py` içindeki `evaluate_holdout()` fonksiyonunda loader ve `src/evaluation/metrics.py` üzerinden okunur. Holdout sonuçlarına bakılarak hiçbir kural değiştirilmedi.

**Tasarımın kaynağı:** Kural listesi (R01-R12), şema, conflict resolution sırası ve skor formülü kullanıcının verdiği tasarımdır (zaman kısıtı nedeniyle bu adımda seçenek turu yapılmadı). Tasarımın belirtmediği noktalarda verilen uygulama kararları "Tasarımdan sapmalar ve uyarlamalar" bölümündedir; özellikle **risk_boost değerleri ve tavanı** tasarımda yoktu ve kullanıcı onayı bekler.

## Ne yapıldı
Adım 6'nın düzeltilmiş skorunun üzerine YAML/JSON ile tanımlanan, kod değiştirmeden eklenip çıkarılabilen bir kural motoru kuruldu. Akış (Chain of Responsibility):

```
kayıt + adjusted_score_unclipped (Adım 6)
  -> türetilmiş kolonlar (derive.add_derived)
  -> her kuralın koşulu (conditions.evaluate_condition)  -> tetiklenen kurallar
  -> conflict resolution (resolver.resolve)               -> karar, uygulanan / bastırılan kurallar
  -> boost toplamı (tavanlı)                              -> final_score_unclipped
  -> kural kararı yoksa skor eşiği                        -> final_decision
  -> mesaj şablonları gerçek değerlerle                   -> reasons
```

Batch (parquet) ve online (tek kayıt) yolu aynı fonksiyonları kullanır: tek kayıt tek satırlı DataFrame olarak işlenir. Script her koşuda 200 satırı (100 rastgele + 100 kural tetiklenmiş) tek kayıt yolundan yeniden değerlendirir ve batch sonucuyla karşılaştırır: tam veride ve örneklemde 0 uyuşmazlık.

| Dosya | İçerik |
|---|---|
| `configs/rules.yaml` | motor ayarları (boost tavanı, karar politikası, girdi kolon kataloğu, öğrenilecek ve dış parametreler) + R01-R10 + `learned:` bloğu |
| `configs/rules_extra.json` | R11, R12 (JSON desteğinin kanıtı) |
| `src/rules/schema.py` | pydantic v2 şeması: `Rule`, `Action`, iç içe `all`/`any`/`not` düğümleri, `Clause` |
| `src/rules/conditions.py` | koşul dilinin vektörel değerlendirmesi |
| `src/rules/repository.py` | `RuleRepository` (YAML + JSON yükleme, `reload()`, istekte gelen kural seti için `parse()`), ad doğrulaması |
| `src/rules/params.py` | fit yüzdelikleri, dış parametre (Adım 6 artifact'ı), `learned:` bloğunu yazma |
| `src/rules/derive.py` | türetilmiş kolonlar ve batch girdisi |
| `src/rules/resolver.py` | conflict resolution |
| `src/rules/explain.py` | mesaj şablonlarını doldurma |
| `src/rules/engine.py` | `RuleEngine` (`RuleEvaluator` arayüzü): `evaluate_batch`, `evaluate(record, score, rules=None)`, `RuleEngineResult` |
| `src/rules/factory.py` | `load_rule_engine` (container bunu kullanır; eğitim yapmaz) |
| `src/rules/report.py` | etiketsiz rapor yardımcıları |
| `scripts/run_rules.py` | uçtan uca çalıştırma (`SAMPLE_N` destekli), `--no-eval` |
| `tests/rules/` | 84 test |

Ortak dosyalara yalnızca ekleme yapıldı: `src/core/interfaces.py`'ye `RuleStore` (reload / parse) ABC'si; `src/container.py`'ye `rule_repository` ve `rule_engine` Singleton'ları. `scripts/run_pipeline.py` içindeki `rules` adımı `scripts/run_rules.py`'yi çalıştırır.

## Kural şeması
```yaml
- id: R01                        # benzersiz (dosyalar arasında da)
  name: card_testing
  description: ...
  priority: 1                    # 1 = en yüksek
  severity: critical             # low | medium | high | critical
  condition:                     # all / any / not iç içe
    all:
      - {feature: TransactionAmt, op: "<=", value: {param: amount_small}}
      - {feature: small_amt_streak_1h, op: ">=", value: 2}
  action: {risk_boost: 0.30, decision: block, flag: card_testing}
  message: "Kart testi şüphesi: {TransactionAmt:.2f} USD küçük tutar ..."
  tags: [card_testing, velocity]
  enabled: true
```
- Operatörler: `> >= < <= == != in not_in between is_null contains`. `between` = `[alt, üst]` (kapalı aralık); `is_null` değeri `true` (varsayılan) / `false`.
- Eksik değer (NaN/None) hiçbir karşılaştırmayı sağlamaz; yalnızca `is_null` görür. `not` düğümü NaN'lı bir koşulu "doğru" yapar (R10'daki `not` kart testi koşulunda kolon hiç boş değildir).
- `{param: ad}` fit'ten öğrenilen veya başka adımın artifact'ından okunan eşiktir.
- Yükleme anında reddedilenler: şema hatası (bilinmeyen anahtar, geçersiz severity/decision/op, `between` için 2 değer olmaması, `in` için liste olmaması, priority < 1), yinelenen id, katalogda olmayan feature adı (ör. `isFraud`), tanımsız parametre, mesaj şablonunda bilinmeyen alan, pozitif boost'lu `allow` veya negatif boost'lu `block/review`. Geçersiz dosyada `reload()` hata verir ve önceki geçerli kural seti korunur.
- Koşullarda kullanılabilecek adlar `configs/rules.yaml` `inputs:` kataloğundaki kolonlar + türetilmiş kolonlardır.

## Girdiler ve türetilen feature'lar
| Kaynak | Kolonlar |
|---|---|
| features.parquet (Adım 3, yalnızca geçmiş) | `small_amt_streak_1h`, `ent_cnt_1h`, `ent_txn_count`, `ent_age_days`, `ent_avg_amt`, `amt_ratio_to_ent_avg`, `amt_zscore_ent`, `is_first_seen`, `card_age_days`, `foreign_addr2`, `addr2_missing`, `is_low_volume_window`, `local_hour_est`, `is_weekend`, `has_identity`, `email_mismatch`, `amt_has_3dec`, `holiday_season`, `device_ent_match` |
| merged.parquet (TransactionID ile) | `TransactionAmt`, `ProductCD`, `addr2`, `P_emaildomain`, `R_emaildomain` |
| geçmiş (batch'te hesaplanır, online kayıtta gelir) | `email_ent_known` (Adım 6'nın `src/context/inputs.email_known_batch` fonksiyonu yeniden kullanıldı: entity bu e-postayı DAHA ÖNCEKİ bir işlemde kullanmış mı) |
| Adım 6 (`reports/scores/adjusted_score.parquet`) | `anomaly_score` (= Adım 5 `anomaly_score_norm`), `adjusted_score` (kırpılmış), `adjusted_score_unclipped` (kuralların arttırdığı ve sıralamanın yapıldığı skor), eşitlik kırıcı `raw_anomaly_score` |

Gereken feature'ların neredeyse tamamı features.parquet'te vardı (son 1 saatteki önceki küçük işlem sayısı = `small_amt_streak_1h`, Adım 3). Yeni türetilenler (`src/rules/derive.py`, batch ve tek kayıtta aynı kod, girdileri yalnızca geçmiş olduğu için kendileri de yalnızca geçmiş):
- `ent_daily_avg` = `ent_txn_count / max(ent_age_days, 1)`: entity'nin geçmiş günlük ortalaması (Adım 6'daki tanımla aynı).
- `burst_ratio_1h` = `ent_cnt_1h / ent_daily_avg` (geçmişi olmayan entity'de NaN, R03 tetiklenmez).
- `known_device` = `device_ent_match >= 1`, `known_email` = `email_ent_known == 1` (Adım 6 C4 ile aynı).

## Eşikler: nerede hesaplanır, nerede tutulur
Eşikler kodda değil config'tedir. `configs/rules.yaml` `learned_params:` her eşiğin tanımını (kolon + yüzdelik) tutar; `scripts/run_rules.py` bunları **yalnızca fit satırlarından** hesaplar ve:
- tam veri koşusunda `configs/rules.yaml` sonundaki `learned:` bloğuna yazar (Adım 3'ün `entity.yaml` `learned:` yöntemiyle aynı; işaret satırının üstü korunur) ve kopyasını `reports/rules/rule_params.json`'a koyar. API/container eşikleri buradan okur, istek anında hesaplama yapmaz.
- `SAMPLE_N` koşusunda config'e dokunmaz; `reports/rules/sample/rule_params.json` yazar.

Dış parametre (`external_params:`): R10'un geçmiş eşiği Adım 6 C4'ün öğrendiği `trusted_min_history` değeridir ve `artifacts/context/context_params.json`'dan okunur (örneklemde `artifacts/context/sample/`); burada yeniden öğrenilmez.

| Parametre | Tanım | Tam veri | Örneklem |
|---|---|---|---|
| `amount_small` | fit TransactionAmt q10 (Adım 3 `small_amt_threshold` ile aynı, script kontrol eder) | 25,95 | 25,00 |
| `amount_high` | fit TransactionAmt q95 (tüm "yüksek tutar" koşulları) | 441,95 | 400,00 |
| `velocity_1h_extreme` | fit `ent_cnt_1h` q99,9 | 12 | 7 |
| `score_review_threshold` | fit `adjusted_score_unclipped` q99 (kural kararı yoksa skorla inceleme) | 1,0696 | 1,1166 |
| `trusted_min_history` | Adım 6 C4, fit `ent_txn_count` q90 (dış) | 809 | 51 |

n_fit = 472.432 (örneklem 40.000).

## Kurallar
Tetiklenme payları etiketsizdir (`reports/rules/rule_coverage.csv`); precision ve lift holdout etiketiyle yalnızca raporlamadır (`reports/rules/rule_metrics.csv`; holdout 118.108 satır, 4.064 pozitif, taban oranı %3,44; lift = precision / taban oranı).

| ID | Koşul | Öncelik | Önem | Karar | Boost | Fit tetiklenme | Holdout tetiklenme | Holdout precision | Lift |
|---|---|---|---|---|---|---|---|---|---|
| R01 | Card testing: tutar <= q10 ve `small_amt_streak_1h >= 2` | 1 | critical | block | +0,30 | 4.854 (%1,03) | 1.129 (%0,96) | 0,131 | 3,81 |
| R02 | Tutar >= q95, `foreign_addr2 = 1`, `is_low_volume_window = 1` | 1 | critical | block | +0,30 | 1 | 1 | 0 (n=1) | - |
| R03 | `ent_cnt_1h >= q99,9` (12) ve `burst_ratio_1h > 3` | 2 | high | review | +0,15 | 53 (%0,01) | 1.128 (%0,96) | 0,000 | 0,00 |
| R04 | Yeni kart (`card_age_days = 0`) ve tutar >= q95 | 2 | high | review | +0,15 | 14.849 (%3,14) | 3.675 (%3,11) | 0,046 | 1,33 |
| R05 | Tutar >= q95 ve `foreign_addr2 = 1` | 2 | high | review | +0,15 | 54 | 4 | 0,25 (n=4) | 7,27 |
| R06 | `amt_ratio_to_ent_avg >= 5` ve `ent_txn_count >= 5` | 3 | medium | review | +0,08 | 7.624 (%1,61) | 2.094 (%1,77) | 0,044 | 1,28 |
| R07 | `is_first_seen = 1` ve tutar >= q95 | 3 | medium | review | +0,08 | 2.207 (%0,47) | 294 (%0,25) | 0,061 | 1,78 |
| R08 | `has_identity = 0`, tutar >= q95, `ProductCD != W` | 3 | medium | review | +0,08 | 3 | 1 | 0 (n=1) | - |
| R09 | `email_mismatch = 1` (P ve R dolu, farklı) ve tutar >= q95 | 4 | low | review | +0,03 | 472 (%0,10) | 62 (%0,05) | 0,339 | 9,84 |
| R10 | C4 trusted (geçmiş >= 809, yaş >= 30 gün, z ∈ [-2, 2], bilinen cihaz VE e-posta) ve kart testi yok | 5 | low | allow | 0 | 7.350 (%1,56) | 3.830 (%3,24) | 0,106 | 3,07 |
| R11 (JSON) | `amt_has_3dec = 1`, `addr2` boş (`is_null`), tutar >= q95 | 3 | medium | review | +0,08 | 4 | 0 | - | - |
| R12 (JSON) | `holiday_season = 1`, yeni kart, tutar >= q95 | 3 | medium | review | +0,08 | 1.300 (%0,28) | 0 | - | - |

Gerekçeler (iş mantığı):
- **R01:** Aynı kart grubunda kısa sürede art arda küçük tutarlar klasik kart testi kalıbıdır (çalıntı kartın çalışıp çalışmadığı denenir). Adım 6'da G1 koruması bu sinyalin indirimle gizlenmesini engelliyordu; burada doğrudan block kararı verir.
- **R02 / R05:** Yabancı ülkede yüksek tutar sınır ötesi kart kullanımı riskidir; düşük hacimli saatte (tahmini yerel 00-06) olması hesap ele geçirme kalıbını güçlendirir (R02 critical, R05 high). R02 tetiklenirse R05 de tetiklenir (R02 ⊂ R05); bastırma sayesinde iki boost birlikte uygulanmaz.
- **R03:** Kendi geçmiş günlük ortalamasının 3 katından fazla bir saatlik patlama, sık işlem yapan entity'nin normal ritmini (Adım 6 C5) gerçek bir değişimden ayırır.
- **R04 / R07:** Kartın ilk gününde veya entity'nin ilk işleminde büyük alışveriş bust-out / çalıntı kart kalıbıdır; gerçek yeni müşteri genelde küçük başlar.
- **R06:** Entity'nin kendi ortalamasının 5 katı; en az 5 geçmiş işlem şartı ortalamanın anlamlı olmasını sağlar.
- **R08:** Cihaz/kimlik verisi olmayan yüksek tutar doğrulanamaz. W ürününde identity kaydı hiç olmadığı için (Adım 1) W hariç tutulur; aksi halde kural yalnızca "W ürünü" demek olurdu.
- **R09 (düşük önem):** Alıcı ve gönderen e-posta alanının farklı olması hediye/dropshipping gibi meşru nedenlerle de olur. EDA'da P = R etkisi ProductCD ile karışıktır (docs/eda.md bulgu 2: W'de identity yok ve W en düşük fraud oranlı ürün; iki değişken ProductCD içinde ayrı incelenmedi). Etkisi ayrıştırılamadığı için en düşük önem ve en küçük boost verildi.
- **R10:** Adım 6'daki revize C4 tanımı (K-20a): uzun geçmiş + kendi normal tutarı + tanıdık cihaz VE e-posta. Kart testi sinyali varsa güven geçersizdir (`not` düğümü).
- **R11:** Ülke kodu yok + kur çevrimi görünümlü tutar + yüksek tutar: kaynağı doğrulanamayan yabancı işlem (varsayım 7).
- **R12:** Tatil tepesinde yeni kartla büyük alışveriş: yoğunluk içinde gizlenen bust-out.

## Conflict resolution
```
resolve(tetiklenen kurallar):
  sırala: (priority artan, severity azalan, karar azalan [block > review > allow], id)
  risk   = block/review kuralları (sıralı), allows = allow kuralları (sıralı)
  kazanan = allows[0]  eğer allow varsa VE (risk boşsa VEYA allows[0].priority < risk[0].priority)
            risk[0]    aksi halde
  final_decision = kazanan.karar
  uygulanan  = kararı final_decision ile aynı olan tüm tetiklenen kurallar
  bastırılan = diğerleri, nedeniyle (daha yüksek öncelik / aynı öncelikte daha yüksek önem /
               aynı öncelik ve önemde karar sırası / "allow, eşit veya daha yüksek öncelikli
               block/review varken uygulanmaz")
  boost = clip(Σ uygulanan.risk_boost, -0,10, +0,40)
final_score_unclipped = adjusted_score_unclipped + boost      # alarm sıralaması bununla
final_score           = clip(final_score_unclipped, 0, 1)     # yalnızca çıktı/gösterim
hiç karar kuralı yoksa: final_score_unclipped >= score_review_threshold ise review ("score"),
                         değilse allow ("default")
```
- Bastırılan kuralların boost'u uygulanmaz: iç içe kurallarda (R02 ⊂ R05) aynı kanıtın iki kez sayılmasını önler. Aynı kararı veren bağımsız kurallar (ör. R04 + R06, ikisi de review) toplanır, tavanla sınırlanır.
- Allow kuralı skor eşiğine üstün gelir: R10 tetiklenmiş ve block/review yoksa skor ne olursa olsun karar allow'dur (R10'un boost'u 0; skoru değiştirmez, yalnızca kararı).
- Çözüm yalnızca hangi kuralların tetiklendiğine bağlı olduğu için batch'te her farklı tetiklenme deseni için bir kez hesaplanır ve satırlara dağıtılır (590k satır ~3 sn).

### Çakışan kurallı örnek kayıtlar (gerçek veri, `reports/rules/conflict_examples.json`)
Holdout'ta yalnızca 1 çakışma var (küçük tutar ve yüksek tutar kuralları birbirini dışlar); örnekler etiketsiz olarak tüm satırlardan seçildi (her farklı "kazanan > bastırılan" birleşimi için en yüksek final skorlu satır, allow'un bastırıldığı birleşimler önce). Çakışma sayıları (`conflicts.csv`): fit'te R01 > R03 (5), R04 > R10 (2), R02 > R04 (1), R02 > R05 (1); holdout'ta R02 > R05 (1).

1. **TransactionID 3223234 (fit) - allow bastırılır.** R04 (p2, high, review) ve R10 (p5, low, allow) tetiklenir. Karar review; R10 bastırılır: "R04 kazandı (öncelik 2, high, review): allow kuralı, eşit veya daha yüksek öncelikli bir block/review varken uygulanmaz". Güvenilir entity (963 önceki işlem, 64 gün, z = 1,51) olsa da yeni kartla 450 USD (eşik 441,95) incelemeye düşer. Skor 0,816 + 0,15 = 0,966.
2. **TransactionID 3124924 (fit) - üç kural, öncelik.** R02 (p1, critical, block), R04 ve R05 (p2, high, review). Karar block; R04 ve R05 "daha yüksek öncelik (1 < 2)" nedeniyle bastırılır, yalnızca R02'nin +0,30'u uygulanır (üçü toplansa +0,60 olurdu).
3. **TransactionID 3516595 (holdout).** R02 + R05; karar block, R05 bastırılır. Kırpılmamış skor 1,347 + 0,30 = 1,647; çıktı skoru 1,0.
4. **TransactionID 3199346 (fit).** R01 (kart testi: 22,91 USD, son 1 saatte 18 küçük işlem) + R03 (son 1 saatte 19 işlem, günlük ortalama 5,5, oran 3,5x). Karar block; R03 bastırılır.

Örnek çıktı (3124924, kısaltılmış):
```json
{
  "transaction_id": 3124924,
  "part": "fit",
  "triggered_rules": [
    {"id": "R02", "name": "high_amount_foreign_low_volume", "priority": 1, "severity": "critical", "decision": "block", "risk_boost": 0.3},
    {"id": "R04", "name": "new_card_high_amount", "priority": 2, "severity": "high", "decision": "review", "risk_boost": 0.15},
    {"id": "R05", "name": "high_amount_foreign", "priority": 2, "severity": "high", "decision": "review", "risk_boost": 0.15}
  ],
  "applied_rules": ["R02"],
  "suppressed_rules": [
    {"id": "R04", "reason": "R02 kazandı (öncelik 1, critical, block): daha yüksek öncelik (1 < 2)",
     "message": "Yeni kart (D1=0) ile yüksek tutar: 500.00 USD (eşik 441.95)."},
    {"id": "R05", "reason": "R02 kazandı (öncelik 1, critical, block): daha yüksek öncelik (1 < 2)",
     "message": "Yabancı ülke kodu addr2=96 ile yüksek tutar: 500.00 USD (eşik 441.95)."}
  ],
  "final_decision": "block",
  "decision_source": "R02",
  "flags": ["foreign_night_high_amount"],
  "reasons": ["Yüksek tutar 500.00 USD (eşik 441.95), yabancı ülke kodu addr2=96 ve düşük hacimli saat (tahmini yerel saat 0)."],
  "anomaly_score": 0.9939,
  "adjusted_score": 1.0,
  "adjusted_score_unclipped": 1.4908,
  "boost_total": 0.3,
  "final_score": 1.0,
  "final_score_unclipped": 1.7908
}
```
Kural kararı yoksa `reasons` skor satırını içerir (ör. "Karar kuralı tetiklenmedi; skor 1.120 inceleme eşiğinin (1.070) üzerinde."); boost tavana takılırsa bir satır daha eklenir. Testlerde sentetik çakışma örnekleri de var (`tests/rules/test_resolver.py`).

## Dinamik çalışma
- `RuleRepository(configs/rules.yaml)`: `files.rules` listesindeki tüm dosyaları (YAML ve JSON) yükler; `reload()` kodu değiştirmeden yeni kural setini okur (geçersizse eski set korunur). Yeni kural eklemek = YAML/JSON'a bir blok eklemek.
- `RuleEngine.evaluate(record, anomaly_score, rules=None)`: `rules` verilirse (JSON metni, `{"rules": [...]}` veya liste) aynı şema ve ad doğrulamasından geçirilir ve yalnızca o çağrıda kullanılır; yüklü set değişmez. `anomaly_score` = Adım 6 `adjusted_score_unclipped`; kayıt gösterim için `anomaly_score` (Adım 5) ve `adjusted_score` taşıyabilir. Eksik girdi kolonu `KeyError` verir.
- Container: `Container.rule_repository` ve `Container.rule_engine` (Singleton). Testlerde `container.rule_engine.override(...)` ile değiştirilebilir.

## Çıktılar (`reports/rules/`, örneklem `reports/rules/sample/`)
| Dosya | Şema |
|---|---|
| `rule_hits.parquet` | index TransactionID; `raw_anomaly_score`, `anomaly_score`, `adjusted_score`, `adjusted_score_unclipped`, `triggered_rules` (liste), `applied_rules`, `suppressed_rules`, `suppressed_reasons`, `boost_raw`, `boost`, `final_score_unclipped`, `final_score` [0,1], `final_decision`, `decision_source` (kazanan kural id / `score` / `default`), `hit_<id>` (int8). Parquet gitignore'da. |
| `rule_params.json` | öğrenilen + dış parametreler |
| `rule_coverage.csv` | kural başına fit/holdout tetiklenme, pay, uygulanan, bastırılan, kazanan (etiketsiz) |
| `decision_distribution.csv` | parça x karar x kaynak (rule/score/default) (etiketsiz) |
| `conflicts.csv`, `conflict_examples.json` | kazanan-bastırılan çiftleri; açıklamalı örnekler (etiketsiz) |
| `score_effect.csv` | boost alan satırlar, ortalama boost, tavana takılan, ortalama skorlar (etiketsiz) |
| `rule_metrics.csv` | holdout: hits, coverage, tp, precision, lift, uygulanan ve onun precision'ı |
| `decision_metrics.csv` | holdout: karar başına satır, tp, fp, precision, lift |
| `budget_comparison.csv` | %1/%5 bütçede Adım 5 / Adım 6 / Adım 7 (alarm, tp, fp, precision, recall, PR-AUC, ROC-AUC) |
| `rule_ablation.csv` | kural kural çıkarma (aynı tetiklenmeler, kural çıkarılıp yeniden çözülür) |
| `holdout_base.csv` | holdout boyutu, pozitif, taban oranı |

## Karar dağılımı (etiketsiz)
| Parça | allow (varsayılan) | allow (R10) | block (kural) | review (kural) | review (skor) |
|---|---|---|---|---|---|
| fit (472.432) | %92,80 | %1,56 | %1,03 | %3,88 | %0,74 |
| holdout (118.108) | 106.894 (%90,51) | 3.830 (%3,24) | 1.130 (%0,96) | 5.621 (%4,76) | 633 (%0,54) |

Skor etkisi (holdout): 6.751 satır (%5,7) boost alır, ortalama +0,186; tavana takılan satır 0 (fit'te 6). Ortalama kırpılmamış skor 0,452 -> 0,463.

## Değerlendirme (holdout; yalnızca raporlama)
Karar bazında (`decision_metrics.csv`):

| Karar | Satır | TP | FP | Precision | Lift |
|---|---|---|---|---|---|
| block | 1.130 | 148 | 982 | 0,131 | 3,81 |
| review | 6.254 | 339 | 5.915 | 0,054 | 1,58 |
| allow | 110.724 | 3.577 | 107.147 | 0,032 | 0,94 |

Bütçe bazında, sıralama kırpılmamış skorla, eşitlikler Adım 5 ham toplamıyla (`budget_comparison.csv`):

| Bütçe | Skor | Alarm | TP | FP | Precision | Recall | PR-AUC |
|---|---|---|---|---|---|---|---|
| %1 | Adım 5 (`anomaly_score_norm`) | 1.182 | 187 | 995 | 0,158 | 0,046 | 0,081 |
| %1 | Adım 6 (`adjusted_score_unclipped`) | 1.182 | 199 | 983 | 0,168 | 0,049 | 0,094 |
| %1 | **Adım 7 (`final_score_unclipped`)** | 1.182 | 184 | **998** | 0,156 | 0,045 | 0,079 |
| %5 | Adım 5 | 5.906 | 684 | 5.222 | 0,116 | 0,168 | 0,081 |
| %5 | Adım 6 | 5.906 | 838 | 5.068 | 0,142 | 0,206 | 0,094 |
| %5 | **Adım 7** | 5.906 | 653 | **5.253** | 0,111 | 0,161 | 0,079 |

ROC-AUC 0,683 / 0,686 / 0,682.

**Sonuç: kural boost'ları bu holdout'ta alarm sıralamasını iyileştirmedi.** Adım 6'ya göre FP %1'de +15 (983 -> 998), %5'te +185 (5.068 -> 5.253); Adım 5'e göre de hafif kötü. Kurallar bu sonuca göre değiştirilmedi (etiketle ayar yasak, K-20b ilkesi). Etiketsiz alarm profili: %1 bütçenin 1.161/1.182'si boost almış satırlardır ve 901 satır Adım 6'nın %1 kümesinde yoktu (yeni girenlerin 792'si R01); %5 bütçede 1.999 yeni satır (R04 908, R03 712, R06 518, R01 355).

Kural çıkarma (`rule_ablation.csv`, betimleyici):

| Varyant | PR-AUC | FP@%1 | FP@%5 |
|---|---|---|---|
| tüm kurallar | 0,0785 | 998 | 5.253 |
| R01'siz | 0,0763 | 1.065 | 5.257 |
| R03'süz | 0,0822 | 998 | 5.134 |
| R04'süz | 0,0819 | 1.003 | 5.188 |
| R06'sız | 0,0799 | 992 | 5.224 |
| R07'siz | 0,0787 | 998 | 5.239 |
| diğerleri (R02, R05, R08-R12) | ~0,0785 | 998 | 5.253 |

Yorum (betimleyici; hiçbir kural bu tabloya göre değiştirilmedi):
- **R01 (card testing) en değerli kural:** precision 0,131 (lift 3,8); çıkarılınca %1'de FP 998 -> 1.065. Block kararlarının tamamına yakını R01'dir.
- **R03 zararlı ve tek bir entity'den ibaret:** holdout'taki 1.128 tetiklenmenin 1.123'ü Adım 5'te bulunan burst entity'si (card1 15775, addr1 330); precision 0. Fit'te bu entity'nin patlaması yoktu (fit tetiklenme 53), eşik (q99,9 = 12) fit'te anlamlıydı. Aynı entity'yi Adım 6 C5 de hedeflemiş ama yakalayamamıştı. Kural tanım olarak doğru çalışıyor (gerçekten kendi ortalamasının 3 katından fazla patlama), ancak bu patlama etiketlere göre dolandırıcılık değil.
- **R04 kapsamı geniş, lift düşük:** holdout'un %3,1'i, lift 1,33; +0,15 boost bu satırları %5 bütçesine taşıyor. D1 = 0'ın "yeni kart" yorumu bir varsayımdır (varsayım 5).
- **R10 "trusted" satırları riskli:** allow verilen 3.830 holdout satırının precision'ı 0,106 (lift 3,1). Adım 6'daki bulguyla tutarlı: entity bir kart GRUBU (card1 + addr1, K-05) ve etiket aynı kart/e-postaya yayılıyor (varsayım 9); uzun geçmişli, tanıdık cihazlı gruplar dolandırıcılık geçmişi de taşıyor. R10 boost'u 0 olduğu için sıralamayı etkilemez, yalnızca kararı allow yapar. Bu, karar katmanında bilinen bir risk olarak kayıtlıdır.
- **R09 ve R05 yüksek precision ama çok az satır** (62 ve 4); istatistiksel olarak güvenilmez.
- **R02, R08, R11 neredeyse hiç tetiklenmez** (fit 1 / 3 / 4): yabancı addr2 satırların %0,8'i, identity'siz C/H/R/S nadir, 3 ondalıklı tutarlar çoğunlukla küçük (C ürünü). **R12 holdout'ta hiç tetiklenmez** (öğrenilen sezon fit döneminde, Adım 6 C7 ile aynı durum).

Örneklem koşusu (SAMPLE_N=50000; 10.000 holdout, 228 pozitif; yalnızca duman testi): %1'de FP 88 / 89 / 88, %5'te 468 / 456 / 468 (Adım 5 / 6 / 7); holdout'ta çakışma yok, örnek 1 satır (3021794). Örneklem ~2 hafta olduğu için R10 hiç tetiklenmez (yaş >= 30 gün sağlanmaz).

## Tasarımdan sapmalar ve uyarlamalar
1. **risk_boost değerleri ve tavanı tasarımda yoktu.** Önem seviyesine göre elle seçildi (etiketsiz): critical +0,30, high +0,15, medium +0,08, low +0,03, allow 0; toplam [-0,10, +0,40] aralığına kırpılır. Gerekçe: Adım 6 skoru ~[0, 1,5] aralığında; critical bir kural skoru bütçe kesiminin üstüne taşıyabilmeli, low bir kural yalnızca eşitliği bozmalı. Değerler config'tedir; **kullanıcı onayı bekler.**
2. **"Yüksek tutar" tüm kurallarda fit q95** (tasarım R02 için q95 diyordu; diğerlerinde aynı eşik kullanıldı). Adım 6 C2/C8 q90 kullanır; iki katmanın eşikleri farklıdır (bağlam düzeltmesi daha geniş, kural daha seçici).
3. **R03 "3 katı" yorumu:** `ent_cnt_1h / ent_daily_avg > 3` (son 1 saatteki önceki işlem sayısı, günlük ortalamanın 3 katından fazla). Alternatif yorum `ent_cnt_24h / ent_daily_avg > 3` (Adım 6 C5'in tersi) olabilirdi; 1 saat tanımı koşulun ilk yarısıyla aynı pencereyi kullanır.
4. **R02/R05 "yabancı ülke"** = Adım 3'ün `foreign_addr2` feature'ı (addr2 dolu ve fit baskın değeri 87'den farklı), yeniden öğrenilmedi. "Düşük hacim penceresi" = `is_low_volume_window` (K-06).
5. **R10'un boost'u 0:** C4 zaten skoru x0,75 indirdi; ikinci bir indirim aynı kanıtı iki kez saymak olurdu. R10 yalnızca kararı etkiler.
6. **Skor tabanlı inceleme eklendi** (skill: "kural kararı + skor eşiği"): hiçbir karar kuralı tetiklenmezse `final_score_unclipped >=` fit q99 ise review. `decision.score_review.enabled: false` ile kapatılır. Allow kuralı buna üstün gelir.
7. **Bastırılan kuralların boost'u uygulanmaz** (tasarımda "sum(boost)" hangi kurallar üzerinden belirtilmemişti); iç içe kurallarda çift sayımı önler.
8. **Kural 4 yorumu:** allow, *eşit veya* daha yüksek öncelikli bir block/review varken uygulanmaz (aynı öncelikte daha yüksek önemli bir allow da review'a yenilir).
9. **Şema ekleri:** `contains` operatörü (skill listesinde var); allow kuralında pozitif, block/review kuralında negatif boost reddedilir; mesaj şablonundaki alanlar yüklemede doğrulanır.
10. **Çakışma örnekleri tüm satırlardan** seçildi (holdout'ta yalnızca 1 çakışma var); her örnekte `part` alanı var.
11. **Etiketli metrikler** (`rule_metrics`, `decision_metrics`, bütçe, ablation) Adım 6'daki gibi `scripts/run_rules.py::evaluate_holdout()` içinde, loader ve `src/evaluation/metrics.py` ile hesaplanır; kural başına precision/lift için `src/evaluation/` altına yardımcı yazılmadı (yazma alanı dışında).
12. **`email_ent_known`** Adım 6'nın fonksiyonuyla hesaplanır (`src/rules` -> `src/context` yatay import; kopya kod yok).

## Bilinen sınırlar
- **Kurallar holdout'ta sıralamayı kötüleştirdi** (Adım 6'ya göre %1'de +15, %5'te +185 FP). Ana kaynaklar R03 (tek entity, precision 0) ve R04 (geniş kapsam, düşük lift); R01 belirgin fayda sağlıyor. Etiketle ayar yasağı nedeniyle değiştirilmedi. Doğru yöntem: boost/eşik/kural seçimini holdout'tan ayrı bir doğrulama döneminde (ör. fit'in son dilimi) yapmak.
- **R10 allow kararları ortalamadan riskli** (precision 0,106); "trusted" tanımı kart grubu entity'siyle düşük risk anlamına gelmiyor. Online kullanımda allow kararının skor tabanlı incelemeyi ezmesi bu nedenle risklidir.
- **Boost değerleri elle seçildi** ve sonuç bunlara duyarlı; güven aralığı hesaplanmadı, tek holdout.
- R02, R08, R11 neredeyse hiç tetiklenmez; R12 holdout'ta ölçülemez (sezon fit'te); R05/R09 çok az satırla ölçüldü.
- Kural kararı ile bütçe sıralaması ayrı kavramlardır: %5 bütçedeki 5.906 alarmın 1.454'ü allow kararlıdır (hepsi "default": hiçbir kural tetiklenmemiş ve skor `score_review_threshold` altında). Karar eşiği fit q99'dur, bütçe holdout'un %5'i.
- Varsayımlara bağlı kurallar: addr2 = 87 = ABD (R02, R05, R11), D1 = kart yaşı (R04, R12), saat dilimi/düşük hacim penceresi (R02), 3 ondalık = kur çevrimi (R11) (docs/assumptions.md).
- Online kayıt `inputs:` kataloğundaki kolonları ve `email_ent_known`'u taşımalıdır; eksik kolon `KeyError` verir.
- Mesaj şablonları Türkçe, sayılar nokta ondalıkla yazılır (Python format).

## Testler (tests/rules, 84 test)
Her kural (R01-R12) için tetiklenen ve tetiklenmeyen (sınırda) kayıt; nötr kayıt; yüklü her kuralın bir test vakası olması; conflict resolution (öncelik, önem, karar sırası, allow'un eşit/yüksek öncelikli review'a yenilmesi, allow'un düşük öncelikli review'u yenmesi, boost tavanı, gerçek kural setiyle R02 > R04/R05 ve R04 > R10 örnekleri); skor tabanlı inceleme ve allow'un ona üstünlüğü; YAML + JSON yükleme, `reload()`, geçersiz dosyada eski setin korunması, dosyalar arası yinelenen id, yalnızca-YAML kurulum; 11 geçersiz kural vakasının reddi (bilinmeyen feature `isFraud` dahil); istekte gelen JSON kural setinin kullanılması ve doğrulanması; tüm operatörler, NaN/None davranışı, `any`/`not`/`all` iç içe; **batch = tek kayıt** (300 sentetik satır); türetilmiş kolonlar; fit yüzdelikleri; `learned:` bloğu gidiş-dönüş; dış parametre okuma; mesajda eksik değer; container provider'ları ve override; `src/rules` ve kural config'lerinde `isFraud` geçmemesi.

## Komutlar
Örneklem: `SAMPLE_N=50000 python scripts/run_rules.py` (~4 sn; önce Adım 6 örneklem koşusu). Tam veri: `python scripts/run_rules.py` (~23 sn; önce `python scripts/run_context.py`). `make pipeline` veya `python scripts/run_pipeline.py --only rules`. `--no-eval` değerlendirmeyi atlar.

## Bir sonraki adımın girdisi (Adım 8-9: RAG ve agent'lar)
Online: `Container.rule_engine.evaluate(record, adjusted_score_unclipped) -> RuleEngineResult`; `explain_dict()` triggered/suppressed kuralları, kararı, Türkçe gerekçeleri ve üç skoru verir. Batch: `reports/rules/rule_hits.parquet`. Kural açıklamaları (`description`, `message`) ve `docs/step7.md` RAG bilgi tabanına girebilir; agent'lar kural seti değişikliğini `RuleRepository.reload()` veya istekte `rules=` ile deneyebilir.
