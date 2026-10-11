# Adım 7 - Configurable Rule Engine

**isFraud kullanıldı mı: hayır - yalnızca evaluation'da raporlama.** Kural koşulları, eşikler, risk artışları ve öncelikler etiketle seçilmedi. Eşikler fit kümesinin (TransactionDT'ye göre ilk %80) yüzdelikleridir. `src/rules/`, `scripts/run_rules.py` ve `configs/rules*.{yaml,json}` içinde `isFraud` geçmez (testle ve grep ile kontrol edildi). Etiket loader'dan ayrı bir Series olarak gelir ve yalnızca `src/evaluation/rule_metrics.py` ile `src/evaluation/metrics.py` fonksiyonlarının içinde kullanılır; script bu fonksiyonlara etiketsiz maskeler ve skorlar verir. Holdout sonucundan sonra yapılan iki düzeltme (R10, R03) etiketten bağımsız gerekçelere dayanır ve "Düzeltmeler" bölümünde şeffaflık için ayrıca anlatılır (K-25).

**Tasarımın kaynağı:** Kural listesi (R01-R12), şema, conflict resolution sırası ve skor formülü kullanıcının verdiği tasarımdır (zaman kısıtı nedeniyle bu adımda seçenek turu yapılmadı). Boost değerleri geliştirme sırasında önerildi, sonra kullanıcı onayladı (K-23). R10 ve R03 düzeltmeleri ve EDA tutarlılık kontrolü kullanıcı kararıdır (K-25).

## Ne yapıldı
Adım 6'nın düzeltilmiş skorunun üzerine YAML/JSON ile tanımlanan, kod değiştirmeden eklenip çıkarılabilen bir kural motoru kuruldu. Akış (Chain of Responsibility):

```
kayıt + adjusted_score_unclipped (Adım 6)
  -> türetilmiş kolonlar (derive.add_derived)
  -> her kuralın koşulu (conditions.evaluate_condition)   -> ham tetiklenmeler
  -> entity başına cooldown (cooldown.apply_cooldown)     -> tetiklenen kurallar
  -> conflict resolution (resolver.resolve)                -> karar, uygulanan / bastırılan kurallar
  -> boost toplamı (tavanlı)                               -> final_score_unclipped
  -> skor eşiği (kural kararı yoksa veya karar allow ise)  -> final_decision
  -> mesaj şablonları gerçek değerlerle                    -> reasons
```

Batch (parquet) ve online (tek kayıt) yolu aynı fonksiyonları kullanır: tek kayıt tek satırlı DataFrame olarak işlenir. Script her koşuda 250 satırı (100 rastgele, 100 kural tetiklenmiş, 50 cooldown'a takılmış) tek kayıt yolundan, o andaki cooldown durumuyla yeniden değerlendirir ve batch sonucuyla karşılaştırır. Tam veride ve örneklemde fark 0 çıktı.

| Dosya | İçerik |
|---|---|
| `configs/rules.yaml` | motor ayarları (boost tavanı, karar politikası, cooldown anahtarı, girdi kolon kataloğu, öğrenilecek ve dış parametreler) + R01-R10 + `learned:` bloğu |
| `configs/rules_extra.json` | R11, R12 (JSON desteğinin kanıtı) |
| `src/rules/schema.py` | pydantic v2 şeması: `Rule`, `Action`, `Cooldown`, iç içe `all`/`any`/`not` düğümleri, `Clause` |
| `src/rules/conditions.py` | koşul dilinin vektörel değerlendirmesi |
| `src/rules/cooldown.py` | `apply_cooldown` (batch ve online ortak), `CooldownStore` (online durum) |
| `src/rules/repository.py` | `RuleRepository` (YAML + JSON yükleme, `reload()`, istekte gelen kural seti için `parse()`), ad doğrulaması |
| `src/rules/params.py` | fit yüzdelikleri, dış parametre (Adım 6 artifact'ı), `learned:` bloğunu yazma |
| `src/rules/derive.py` | türetilmiş kolonlar ve batch girdisi |
| `src/rules/resolver.py` | conflict resolution |
| `src/rules/explain.py` | mesaj şablonlarını doldurma |
| `src/rules/engine.py` | `RuleEngine` (`RuleEvaluator` arayüzü): `evaluate_batch`, `evaluate(record, score, rules=None, update_state=True)`, `RuleEngineResult` |
| `src/rules/factory.py` | `load_rule_engine` (container bunu kullanır; eğitim yapmaz) |
| `src/rules/report.py` | etiketsiz rapor yardımcıları (kapsama, entity yoğunlaşması, karar dağılımı, örnek seçimi) |
| `src/evaluation/rule_metrics.py` | etiketli metrikler: `rule_hit_metrics`, `decision_metrics`, `budget_table`, `lift_by_group` |
| `scripts/run_rules.py` | uçtan uca çalıştırma (`SAMPLE_N` destekli), `--no-eval` |
| `tests/rules/` (93 test), `tests/evaluation/test_rule_metrics.py` (4 test) | sentetik veriyle testler |

Ortak dosyalara yalnızca ekleme yapıldı: `src/core/interfaces.py`'ye `RuleStore` (reload / parse) ABC'si; `src/container.py`'ye `rule_repository` ve `rule_engine` Singleton'ları. `scripts/run_pipeline.py` içindeki `rules` adımı `scripts/run_rules.py`'yi çalıştırır.

## Kural şeması
```yaml
- id: R03                        # benzersiz (dosyalar arasında da)
  name: velocity_burst
  description: ...
  priority: 2                    # 1 = en yüksek
  severity: high                 # low | medium | high | critical
  condition:                     # all / any / not iç içe
    all:
      - {feature: ent_cnt_1h, op: ">=", value: {param: velocity_1h_extreme}}
      - {feature: burst_ratio_1h, op: ">", value: 3}
  action: {risk_boost: 0.15, decision: review, flag: velocity_burst}
  cooldown: {window_seconds: 3600, key: entity}   # isteğe bağlı
  message: "Velocity patlaması: son 1 saatte {ent_cnt_1h:.0f} önceki işlem ..."
  tags: [velocity]
  enabled: true
```
- Operatörler: `> >= < <= == != in not_in between is_null contains`. `between` = `[alt, üst]` (kapalı aralık); `is_null` değeri `true` (varsayılan) / `false`.
- Eksik değer (NaN/None) hiçbir karşılaştırmayı sağlamaz; yalnızca `is_null` görür. `not` düğümü NaN'lı bir koşulu "doğru" yapar (R10'daki `not` kart testi koşulunda kolon hiç boş değildir).
- `{param: ad}` fit'ten öğrenilen veya başka adımın artifact'ından okunan eşiktir.
- `cooldown` (isteğe bağlı): kural aynı entity için `window_seconds` içinde en fazla bir kez tetiklenir (aşağıda).
- Yükleme anında reddedilenler: şema hatası (bilinmeyen anahtar, geçersiz severity/decision/op, `between` için 2 değer olmaması, `in` için liste olmaması, priority < 1, window < 1), yinelenen id, katalogda olmayan feature adı (ör. `isFraud`), tanımsız parametre, mesaj şablonunda bilinmeyen alan, pozitif boost'lu `allow` veya negatif boost'lu `block/review`. Geçersiz dosyada `reload()` hata verir ve önceki geçerli kural seti korunur.
- Koşullarda kullanılabilecek adlar `configs/rules.yaml` `inputs:` kataloğundaki kolonlar + türetilmiş kolonlardır.

## Girdiler ve türetilen feature'lar
| Kaynak | Kolonlar |
|---|---|
| features.parquet (Adım 3, yalnızca geçmiş) | `small_amt_streak_1h`, `ent_cnt_1h`, `ent_txn_count`, `ent_age_days`, `ent_avg_amt`, `amt_ratio_to_ent_avg`, `amt_zscore_ent`, `is_first_seen`, `card_age_days`, `foreign_addr2`, `addr2_missing`, `is_low_volume_window`, `local_hour_est`, `is_weekend`, `has_identity`, `email_mismatch`, `amt_has_3dec`, `holiday_season`, `device_ent_match` |
| merged.parquet (TransactionID ile) | `TransactionAmt`, `ProductCD`, `addr2`, `P_emaildomain`, `R_emaildomain`; cooldown için `TransactionDT` ve entity kolonları (`configs/entity.yaml`: `card1`, `addr1`) |
| geçmiş (batch'te hesaplanır, online kayıtta gelir) | `email_ent_known` (Adım 6'nın `src/context/inputs.email_known_batch` fonksiyonu yeniden kullanıldı: entity bu e-postayı DAHA ÖNCEKİ bir işlemde kullanmış mı) |
| Adım 6 (`reports/scores/adjusted_score.parquet`) | `anomaly_score` (= Adım 5 `anomaly_score_norm`), `adjusted_score` (kırpılmış), `adjusted_score_unclipped` (kuralların arttırdığı ve sıralamanın yapıldığı skor), eşitlik kırıcı `raw_anomaly_score` |

Gereken feature'ların neredeyse tamamı features.parquet'te vardı (son 1 saatteki önceki küçük işlem sayısı = `small_amt_streak_1h`, Adım 3). Yeni türetilenler (`src/rules/derive.py`, batch ve tek kayıtta aynı kod; girdileri yalnızca geçmişe dayandığı için bunlar da yalnızca geçmişe dayanır):
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
| `score_review_threshold` | fit `adjusted_score_unclipped` q99 (skor tabanlı inceleme) | 1,0696 | 1,1166 |
| `trusted_min_history` | Adım 6 C4, fit `ent_txn_count` q90 (dış) | 809 | 51 |

n_fit = 472.432 (örneklem 40.000). R03 cooldown penceresi 3.600 sn kuralın kendi tanımındadır (`cooldown.window_seconds`).

## Kurallar
Tetiklenme payları ve yoğunlaşma etiketsizdir (`reports/rules/rule_coverage.csv`); precision ve lift holdout etiketiyle yalnızca raporlamadır (`reports/rules/rule_metrics.csv`; holdout 118.108 satır, 4.064 pozitif, taban oranı %3,44; lift = precision / taban oranı). Değerler düzeltilmiş koşudandır.

| ID | Koşul | Öncelik | Önem | Karar | Boost | Fit tetiklenme | Holdout tetiklenme | Holdout precision | Lift |
|---|---|---|---|---|---|---|---|---|---|
| R01 | Card testing: tutar <= q10 ve `small_amt_streak_1h >= 2` | 1 | critical | block | +0,30 | 4.854 (%1,03) | 1.129 (%0,96) | 0,131 | 3,81 |
| R02 | Tutar >= q95, `foreign_addr2 = 1`, `is_low_volume_window = 1` | 1 | critical | block | +0,30 | 1 | 1 | 0 (n=1) | - |
| R03 | `ent_cnt_1h >= q99,9` (12) ve `burst_ratio_1h > 3`; entity başına 1 saatte en fazla bir kez | 2 | high | review | +0,15 | 8 (cooldown öncesi 53) | 21 (cooldown öncesi 1.128) | 0,000 | 0,00 |
| R04 | Yeni kart (`card_age_days = 0`) ve tutar >= q95 | 2 | high | review | +0,15 | 14.849 (%3,14) | 3.675 (%3,11) | 0,046 | 1,33 |
| R05 | Tutar >= q95 ve `foreign_addr2 = 1` | 2 | high | review | +0,15 | 54 | 4 | 0,25 (n=4) | 7,27 |
| R06 | `amt_ratio_to_ent_avg >= 5` ve `ent_txn_count >= 5` | 3 | medium | review | +0,08 | 7.624 (%1,61) | 2.094 (%1,77) | 0,044 | 1,28 |
| R07 | `is_first_seen = 1` ve tutar >= q95 | 3 | medium | review | +0,08 | 2.207 (%0,47) | 294 (%0,25) | 0,061 | 1,78 |
| R08 | `has_identity = 0`, tutar >= q95, `ProductCD != W` | 3 | medium | review | +0,08 | 3 | 1 | 0 (n=1) | - |
| R09 | `email_mismatch = 1` (P ve R dolu, farklı) ve tutar >= q95 | 4 | low | review | +0,03 | 472 (%0,10) | 62 (%0,05) | 0,339 | 9,84 |
| R10 | C4 trusted (geçmiş >= 809, yaş >= 30 gün, z ∈ [-2, 2], bilinen cihaz VE e-posta) ve kart testi yok | 5 | low | allow | 0 | 7.350 (%1,56) | 3.830 (%3,24) | 0,106 | 3,07 |
| R11 (JSON) | `amt_has_3dec = 1`, `addr2` boş (`is_null`), tutar >= q95 | 3 | medium | review | +0,08 | 4 | 0 | - | - |
| R12 (JSON) | `holiday_season = 1`, yeni kart, tutar >= q95 | 3 | medium | review | +0,08 | 1.300 (%0,28) | 0 | - | - |

### Tetiklenme yoğunlaşması (etiketsiz sağlık metriği)
Kuralın tetiklenmelerinin ne kadarının en çok tetiklenen entity'den (top-1) ve en çok tetiklenen 5 entity'den (top-5) geldiğini gösterir. Bu ölçü etiket kullanmaz: tek bir entity'nin davranışını tekrar tekrar sayan bir kural genel bir kalıbı yakalamaz. Kaynak: `rule_coverage.csv` (`*_top1_entity`, `*_top1_entity_share`, `*_top5_entity_share`).

| Kural | Holdout tetiklenme | Top-1 entity | Top-1 payı | Top-5 payı | Fit top-1 / top-5 |
|---|---|---|---|---|---|
| R01 | 1.129 | 15885 / addr1 yok | 0,345 | 0,624 | 0,378 / 0,613 |
| R03 (cooldown öncesi, ilk sürüm) | 1.128 | 15775 / 330 | 0,996 (1.123) | ~1,0 | - |
| R03 (cooldown sonrası) | 21 | 15775 / 330 | 0,904 (19) | 1,000 | 0,25 / 0,75 (n=8) |
| R04 | 3.675 | 16132 / 299 | 0,010 | 0,040 | 0,009 / 0,034 |
| R05 | 4 | 18268 / 512 | 0,25 | 1,0 | 0,22 / 0,48 |
| R06 | 2.094 | 12695 / 325 | 0,012 | 0,042 | 0,013 / 0,053 |
| R07 | 294 | 5756 / 325 | 0,003 | 0,017 | 0,000 / 0,002 |
| R09 | 62 | 14544 / 299 | 0,129 | 0,467 | 0,027 / 0,097 |
| R10 | 3.830 | 15885 / addr1 yok | 0,185 | 0,504 | 0,250 / 0,706 |

R02, R08 ve R11'in tetiklenme sayısı yoğunlaşma ölçmek için çok az, R12 holdout'ta hiç tetiklenmiyor. R01 ve R10'un en yoğun entity'si aynı kart grubudur (card1 15885, addr1 boş): `addr1` boşluğu kendi seviyesi sayıldığı için (K-05) bu "entity" adressiz pek çok kartı birleştirir. Bu bir entity proxy sınırıdır (Bilinen sınırlar).

Gerekçeler (iş mantığı):
- **R01:** Aynı kart grubunda kısa sürede art arda küçük tutarlar klasik kart testi kalıbıdır (çalıntı kartın çalışıp çalışmadığı denenir). Adım 6'da G1 koruması bu sinyalin indirimle gizlenmesini engelliyordu; burada doğrudan block kararı verir.
- **R02 / R05:** Yabancı ülkede yüksek tutar sınır ötesi kart kullanımı riskidir; düşük hacimli saatte (tahmini yerel 00-06) olması hesap ele geçirme kalıbını güçlendirir (R02 critical, R05 high). R02 tetiklenirse R05 de tetiklenir (R02 ⊂ R05); bastırma sayesinde iki boost birlikte uygulanmaz.
- **R03:** Kendi geçmiş günlük ortalamasının 3 katından fazla bir saatlik patlama, sık işlem yapan entity'nin normal ritmini (Adım 6 C5) gerçek bir değişimden ayırır. Cooldown: bir patlama tek bir uyarıdır.
- **R04 / R07:** Kartın ilk gününde veya entity'nin ilk işleminde büyük alışveriş bust-out / çalıntı kart kalıbıdır; gerçek yeni müşteri genelde küçük başlar.
- **R06:** Entity'nin kendi ortalamasının 5 katı; en az 5 geçmiş işlem şartı ortalamanın anlamlı olmasını sağlar.
- **R08:** Cihaz/kimlik verisi olmayan yüksek tutar doğrulanamaz. W ürününde identity kaydı hiç olmadığı için (Adım 1) W hariç tutulur; aksi halde kural yalnızca "W ürünü" demek olurdu.
- **R09 (düşük önem):** Alıcı ve gönderen e-posta alanının farklı olması hediye/dropshipping gibi meşru nedenlerle de olur. EDA'da P = R etkisi ProductCD ile karışıktır (docs/eda.md bulgu 2). Etkisi ayrıştırılamadığı için en düşük önem ve en küçük boost verildi.
- **R10:** Adım 6'daki revize C4 tanımı (K-20a): uzun geçmiş + kendi normal tutarı + tanıdık cihaz VE e-posta. Kart testi sinyali varsa güven geçersizdir (`not` düğümü).
- **R11:** Ülke kodu yok + kur çevrimi görünümlü tutar + yüksek tutar: kaynağı doğrulanamayan yabancı işlem (varsayım 7).
- **R12:** Tatil tepesinde yeni kartla büyük alışveriş: yoğunluk içinde gizlenen bust-out.

## Cooldown (R03)
- **Tanım:** Bir satırdaki ham tetiklenme, aynı entity'nin son *tutulan* tetiklenmesi en az `window_seconds` (3.600) önceyse tutulur; değilse düşer ve satırın `cooldown_rules` listesine yazılır. Yalnızca önceki satırlara bakar (geçmiş). Düşen kural conflict resolution'a girmez, boost almaz; açıklamada `suppressed_rules` içinde "cooldown: aynı entity için son 3600 sn içinde zaten tetiklendi" nedeniyle görünür.
- **Batch:** `apply_cooldown` satırları TransactionDT sırasıyla (eşitlikte satır sırasıyla) gezer, boş bir durumla başlar ve tüm veriyi (fit + holdout) işler. Bu, Adım 3'ün geçmiş feature'larıyla aynı yaklaşımdır.
- **Online: stateful (durumlu), stateless (durumsuz) türetme değil.** "Son tutulan tetiklenme" bir önceki kararın sonucuna bağlıdır; features.parquet'teki pencere sayılarından türetilemez. Bu yüzden motor, (kural, entity) başına son tetiklenme zamanını tutan bir `CooldownStore` alır. `evaluate()` aynı `apply_cooldown` fonksiyonunu tek satırla bu durum üzerinde çağırır ve tetiklenince durumu günceller. `update_state=False` durumu değiştirmeden değerlendirir. Kural cooldown kullanıyorsa kayıt `TransactionDT`, `card1`, `addr1` alanlarını taşımalıdır.
- **Parity kontrolü:** Script her kontrol satırı için online durumu, batch çıktısındaki o entity'nin satırdan önceki son tutulan R03 tetiklenmesiyle kurar ve tek kayıt yolunu çalıştırır. 250 satırda, cooldown'a takılan 50 satır dahil, fark 0. `tests/rules/test_cooldown.py` sıralı bir patlamayı online yoldan yeniden oynatıp batch ile aynı sonucu aldığını doğrular.
- **Sınır:** `CooldownStore` bellek içidir ve tek süreçte çalışır. Çok süreçli bir API için paylaşılan bir depo (ör. Redis) gerekir. Süreç yeniden başlarsa durum sıfırlanır.

## Conflict resolution
```
resolve(tetiklenen kurallar):                      # cooldown'dan sonra kalanlar
  sırala: (priority artan, severity azalan, karar azalan [block > review > allow], id)
  risk   = block/review kuralları (sıralı), allows = allow kuralları (sıralı)
  kazanan = allows[0]  eğer allow varsa VE hiç block yoksa
                       VE (risk boşsa VEYA allows[0].priority < risk[0].priority)
            risk[0]    aksi halde
  final_decision = kazanan.karar
  uygulanan  = kararı final_decision ile aynı olan tüm tetiklenen kurallar
  bastırılan = diğerleri, nedeniyle
  boost = clip(Σ uygulanan.risk_boost, -0,10, +0,40)
skor eşiği (RuleEngine.decide), boost'tan önceki skorla:
  kural kararı yok      ve adjusted_score_unclipped >= score_review_threshold -> review ("score")
  kazanan allow         ve adjusted_score_unclipped >= score_review_threshold -> review ("score");
                        allow bastırılır, boost'u geri alınır
  kural kararı yok, eşik altı -> allow ("default")
final_score_unclipped = adjusted_score_unclipped + boost      # alarm sıralaması bununla
final_score           = clip(final_score_unclipped, 0, 1)     # yalnızca çıktı/gösterim
```
Kurallar:
1. Küçük priority değeri kazanır.
2. Aynı priority'de yüksek severity kazanır.
3. Aynı priority ve severity'de block > review > allow.
4. **allow yalnızca KURAL kaynaklı ve daha DÜŞÜK öncelikli review kararlarını bastırabilir** (K-25 düzeltmesi):
   - allow ve block (önceliği ne olursa olsun) -> **block**. Neden: "allow, block kararını hiçbir zaman bastıramaz".
   - allow ve eşit/yüksek öncelikli kural review -> **review**. Neden: "allow kuralı, eşit veya daha yüksek öncelikli bir review varken uygulanmaz".
   - allow ve daha düşük öncelikli kural review -> **allow** (mevcut davranış korundu). Review kuralı "daha yüksek öncelik" nedeniyle bastırılır.
   - allow ve skor eşiğinden gelen review -> **review**. Neden: "allow kuralı, skor eşiğinden gelen review kararını bastıramaz".

- Bastırılan kuralların boost'u uygulanmaz: iç içe kurallarda (R02 ⊂ R05) aynı kanıtın iki kez sayılmasını önler. Aynı kararı veren bağımsız kurallar (ör. R04 + R06, ikisi de review) toplanır, tavanla sınırlanır.
- Çözüm yalnızca hangi kuralların tetiklendiğine bağlıdır. Bu yüzden batch'te her farklı tetiklenme deseni için bir kez hesaplanır ve satırlara dağıtılır (590k satır ~3 sn). Skora bağlı kısım (eşik) vektörel uygulanır.
- Tasarım gereği R10 kart testi (R01) satırlarında hiç tetiklenmez (`not` düğümü). R10'un tetiklendiği satırlar C4 indirimi aldığı için skor eşiğine nadiren ulaşır. Bu nedenle kural-4 düzeltmesi **mevcut veride hiçbir satırın kararını değiştirmedi**: allow (R10) sayısı fit'te 7.348, holdout'ta 3.830 olarak kaldı. Düzeltme, kural setinin veya skorların değiştiği durumlar için bir mantık güvencesidir ve testlerle sabitlenmiştir.

### Çakışan kurallı örnek kayıtlar (gerçek veri, `reports/rules/conflict_examples.json`)
Holdout'ta yalnızca 1 çakışma var (küçük tutar ve yüksek tutar kuralları birbirini dışlar). Bu yüzden örnekler etiketsiz olarak tüm satırlardan seçildi: her farklı "kazanan > bastırılan" birleşimi için en yüksek final skorlu satır alındı, allow'un bastırıldığı birleşimler öne kondu. Çakışma sayıları (`conflicts.csv`): fit'te R04 > R10 (2), R02 > R04 (1), R02 > R05 (1), R01 > R03 (1; cooldown öncesi 5); holdout'ta R02 > R05 (1).

1. **TransactionID 3223234 (fit) - allow bastırılır.** R04 (p2, high, review) ve R10 (p5, low, allow) tetiklenir. Karar review. R10 şu nedenle bastırılır: "R04 kazandı (öncelik 2, high, review): allow kuralı, eşit veya daha yüksek öncelikli bir review varken uygulanmaz". Güvenilir entity olsa da (963 önceki işlem, 64 gün, z = 1,51) yeni kartla 450 USD (eşik 441,95) incelemeye düşer. Skor 0,816 + 0,15 = 0,966.
2. **TransactionID 3124924 (fit) - üç kural, öncelik.** R02 (p1, critical, block), R04 ve R05 (p2, high, review). Karar block. R04 ve R05 "daha yüksek öncelik (1 < 2)" nedeniyle bastırılır; yalnızca R02'nin +0,30'u uygulanır (üçü toplansa +0,60 olurdu).
3. **TransactionID 3516595 (holdout).** R02 + R05; karar block, R05 bastırılır. Kırpılmamış skor 1,347 + 0,30 = 1,647; çıktı skoru 1,0.
4. **TransactionID 3199318 (fit).** R01 (kart testi: 22,91 USD, son 1 saatte 16 küçük işlem) + R03 (son 1 saatte 17 işlem, günlük ortalama 5,5, oran 3,1x). Karar block; R03 bastırılır. (İlk sürümdeki 3199346 örneği aynı patlamanın bir sonraki işlemiydi; cooldown nedeniyle orada R03 artık tetiklenmiyor.)

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
Kural kararı yoksa `reasons` bir skor satırı içerir (ör. "Karar kuralı tetiklenmedi; skor 1.120 inceleme eşiğinin (1.070) üzerinde."). Boost tavana takılırsa bir satır daha eklenir. Sentetik çakışma örnekleri testlerde de var (`tests/rules/test_resolver.py`).

## Dinamik çalışma
- `RuleRepository(configs/rules.yaml)`: `files.rules` listesindeki tüm dosyaları (YAML ve JSON) yükler. `reload()` kodu değiştirmeden yeni kural setini okur; dosya geçersizse eski set korunur. Yeni kural eklemek = YAML/JSON'a bir blok eklemek.
- `RuleEngine.evaluate(record, anomaly_score, rules=None, update_state=True)`: `rules` verilirse (JSON metni, `{"rules": [...]}` veya liste) aynı şema ve ad doğrulamasından geçer ve yalnızca o çağrıda kullanılır; yüklü set değişmez. `anomaly_score` = Adım 6 `adjusted_score_unclipped`. Kayıt gösterim için `anomaly_score` (Adım 5) ve `adjusted_score` alanlarını taşıyabilir. Eksik girdi kolonu `KeyError` verir.
- Container: `Container.rule_repository` ve `Container.rule_engine` (Singleton). Motor kendi `CooldownStore`'unu taşır. Testlerde `container.rule_engine.override(...)` ile değiştirilebilir.

## Çıktılar (`reports/rules/`, örneklem `reports/rules/sample/`, ilk sürüm `reports/rules/v1/`)
| Dosya | Şema |
|---|---|
| `rule_hits.parquet` | index TransactionID; `raw_anomaly_score`, `anomaly_score`, `adjusted_score`, `adjusted_score_unclipped`, `triggered_rules` (liste), `applied_rules`, `suppressed_rules`, `suppressed_reasons`, `boost_raw`, `boost`, `final_score_unclipped`, `final_score` [0,1], `final_decision`, `decision_source` (kazanan kural id / `score` / `default`), `cooldown_rules`, `hit_<id>` (int8, cooldown sonrası). Parquet gitignore'da. |
| `rule_params.json` | öğrenilen + dış parametreler |
| `rule_coverage.csv` | kural ve parça başına tetiklenme (cooldown öncesi/sonrası), pay, uygulanan, bastırılan, kazanan, top-1 entity ve top-1/top-5 yoğunlaşma payı (etiketsiz) |
| `decision_distribution.csv` | parça x karar x kaynak (rule/score/default) (etiketsiz) |
| `conflicts.csv`, `conflict_examples.json` | kazanan-bastırılan çiftleri; açıklamalı örnekler (etiketsiz) |
| `score_effect.csv` | boost alan satırlar, ortalama boost, tavana takılan, ortalama skorlar (etiketsiz) |
| `rule_metrics.csv` | holdout: hits, coverage, tp, precision, lift, uygulanan ve onun precision'ı |
| `decision_metrics.csv` | holdout: karar başına satır, tp, fp, precision, lift |
| `budget_comparison.csv` | %1/%5 bütçede Adım 5 / Adım 6 / Adım 7 (alarm, tp, fp, precision, recall, PR-AUC, ROC-AUC) |
| `rule_ablation.csv` | kural kural çıkarma (aynı tetiklenmeler, kural çıkarılıp yeniden çözülür), bütçe başına |
| `eda_fit_vs_holdout.csv` | kural başına fit ve holdout tetiklenme, kapsama, precision, lift yan yana |
| `eda_lift_by_product.csv` | koşul/kural x ProductCD (ve ALL) x parça: grup taban oranı, tetiklenme, precision, grup içi ve genel lift |
| `holdout_base.csv` | holdout boyutu, pozitif, taban oranı |
| `v1/` | ilk sürümün (düzeltme öncesi) tam veri ve örneklem çıktıları, değiştirilmeden saklandı |

## Karar dağılımı (etiketsiz, düzeltilmiş koşu)
| Parça | allow (varsayılan) | allow (R10) | block (kural) | review (kural) | review (skor) |
|---|---|---|---|---|---|
| fit (472.432) | %92,81 | 7.348 (%1,56) | %1,03 | %3,87 | %0,74 |
| holdout (118.108) | 108.001 (%91,44) | 3.830 (%3,24) | 1.130 (%0,96) | 4.514 (%3,82) | 633 (%0,54) |

İlk sürüme göre holdout'ta kural kaynaklı review 5.621'den 4.514'e indi (R03 cooldown, -1.107); bu satırlar varsayılan allow'a geçti. R10 düzeltmesi hiçbir kararı değiştirmedi (yukarıda). Skor etkisi (holdout): 5.644 satır (%4,8) boost alır, ortalama +0,193; tavana takılan satır 0 (fit'te 6).

## Değerlendirme (holdout; yalnızca raporlama)
Karar bazında (`decision_metrics.csv`):

| Karar | Satır | TP | FP | Precision | Lift |
|---|---|---|---|---|---|
| block | 1.130 | 148 | 982 | 0,131 | 3,81 |
| review | 5.147 | 339 | 4.808 | 0,066 | 1,91 |
| allow | 111.831 | 3.577 | 108.254 | 0,032 | 0,93 |

(İlk sürüm: review 6.254 satır, FP 5.915, precision 0,054.)

### Adım 6 / Adım 7 ilk sürüm / Adım 7 düzeltilmiş
Sıralama kırpılmamış skorla, eşitlikler Adım 5 ham toplamıyla. İlk sürümün sayıları düzeltmeden önce `reports/rules/v1/budget_comparison.csv` olarak saklandı.

| Bütçe | Skor | FP | Precision | Recall | PR-AUC |
|---|---|---|---|---|---|
| %1 (1.182 alarm) | Adım 6 (`adjusted_score_unclipped`) | 983 | 0,168 | 0,049 | 0,094 |
| %1 | Adım 7 ilk sürüm | 998 | 0,156 | 0,045 | 0,079 |
| %1 | **Adım 7 düzeltilmiş** | **998** | **0,156** | **0,045** | **0,082** |
| %5 (5.906 alarm) | Adım 6 | 5.068 | 0,142 | 0,206 | 0,094 |
| %5 | Adım 7 ilk sürüm | 5.253 | 0,111 | 0,161 | 0,079 |
| %5 | **Adım 7 düzeltilmiş** | **5.137** | **0,130** | **0,189** | **0,082** |

Referans: Adım 5 (`anomaly_score_norm`) %1'de FP 995, %5'te 5.222, PR-AUC 0,081. ROC-AUC 0,686 (Adım 6), 0,682 (ilk), 0,683 (düzeltilmiş).

**Sonuç:** Düzeltilmiş kural seti de alarm sıralamasını Adım 6'nın üstüne çıkarmıyor. %1'de değişim yok (FP 998, Adım 6'ya göre +15); %5'te ilk sürüme göre 116 FP daha az (5.253 -> 5.137), ama Adım 6'ya göre hâlâ +69. Bu sonuçtan sonra başka bir ayar yapılmadı.

Kural çıkarma, düzeltilmiş koşu (`rule_ablation.csv`, betimleyici):

| Varyant | PR-AUC | FP@%1 | FP@%5 |
|---|---|---|---|
| tüm kurallar | 0,0822 | 998 | 5.137 |
| R01'siz | 0,0813 | 1.051 | 5.149 |
| R03'süz | 0,0822 | 998 | 5.134 |
| R04'süz | 0,0870 | 1.003 | 5.083 |
| R06'sız | 0,0839 | 992 | 5.116 |
| R07'siz | 0,0825 | 998 | 5.130 |
| diğerleri (R02, R05, R08-R12) | ~0,082 | 998 | 5.137 |

Yorum (betimleyici; bu tabloya bakılarak hiçbir kural değiştirilmedi):
- **R01 (card testing) en değerli kural:** precision 0,131 (lift 3,8). Çıkarılınca %1'de FP 998'den 1.051'e çıkıyor. Block kararlarının tamamına yakını R01'den geliyor.
- **R03 cooldown sonrası etkisiz:** 21 tetiklenme, precision 0. Çıkarmak %5'te yalnızca 3 FP fark yaratıyor (ilk sürümde 119 fark).
- **R04 en büyük zarar kaynağı:** holdout'un %3,1'inde tetikleniyor, lift 1,33. +0,15 boost bu satırları %5 bütçesine taşıyor. Kullanıcı kararıyla değiştirilmedi.
- **R10 "trusted" satırları riskli:** allow verilen 3.830 holdout satırının precision'ı 0,106 (lift 3,1). Bu, Adım 6'daki bulguyla tutarlı: entity bir kart grubu (card1 + addr1, K-05) ve etiket aynı kart/e-postaya yayılıyor (varsayım 9). R10'un en yoğun entity'si de adressiz kart grubu 15885 (payı %18,5).

## EDA tutarlılık kontrolü (fit ve holdout)
**Bu tablo kural seçiminde kullanılmadı; kurallar fit EDA'sından önce uzman bilgisiyle tasarlandı. Amaç, fit'te görülen zayıflığın holdout'ta tekrar edip etmediğini göstermek.** Metrikler `src/evaluation/rule_metrics.py` (`rule_hit_metrics`, `lift_by_group`) ile hesaplandı. Dosyalar: `reports/rules/eda_fit_vs_holdout.csv`, `reports/rules/eda_lift_by_product.csv`. Fit taban oranı %3,51, holdout %3,44.

### Kural başına fit ve holdout
| Kural | Fit tetiklenme | Fit lift | Holdout tetiklenme | Holdout lift | Yorum |
|---|---|---|---|---|---|
| R01 | 4.854 | 2,95 | 1.129 | 3,81 | iki dönemde de güçlü |
| R02 | 1 | (n=1) | 1 | (n=1) | ölçülemez |
| R03 | 8 | (n=8) | 21 | 0 | ölçülemez / holdout'ta 0 |
| R04 | 14.849 | 1,25 | 3.675 | 1,33 | iki dönemde de zayıf |
| R05 | 54 | 6,85 | 4 | (n=4) | fit'te güçlü ama az; holdout ölçülemez |
| R06 | 7.624 | **0,98** | 2.094 | 1,28 | fit'te genel sinyal yok, holdout'ta zayıf |
| R07 | 2.207 | 1,16 | 294 | 1,78 | zayıf |
| R08 | 3 | 0 | 1 | 0 | kapsam ihmal edilebilir |
| R09 | 472 | **1,51** | 62 | 9,84 | iki dönem tutarsız (holdout n=62) |
| R10 | 7.350 | 2,26 | 3.830 | 3,07 | "trusted" iki dönemde de ortalamadan riskli |
| R11 | 4 | (n=4) | 0 | - | ölçülemez |
| R12 | 1.300 | 0,59 | 0 | - | fit'te ters yön; holdout'ta sezon yok |

### ProductCD kırılımı (grup içi lift = koşulun gruptaki precision'ı / grubun taban oranı)
Grup içi lift 1'e yakınsa koşulun genel lift'i yalnızca ürün karışımından geliyordur.

| Koşul | Parça | ALL | C | H | R | S | W |
|---|---|---|---|---|---|---|---|
| `foreign_addr2 = 1` | fit | 2,95 (3.931) | 0,78 (3.053) | 4,23 (428) | 3,93 (372) | 0 (8) | 0 (70) |
| | holdout | 2,55 (422) | 0,18 (287) | 1,96 (69) | 9,80 (48) | 0 (1) | 0 (17) |
| `card_age_days = 0` (yeni kart) | fit | 1,18 | 0,99 | 0,96 | 1,07 | 0,72 | 0,88 |
| | holdout | 1,33 | 1,07 | 0,98 | 1,06 | 1,86 | 0,96 |
| `is_low_volume_window = 1` | fit | 2,14 | 2,23 | 2,68 | 2,25 | 1,56 | 1,58 |
| | holdout | 1,61 | 1,84 | 3,29 | 1,72 | 3,12 | 1,37 |
| `email_mismatch = 1` (koşul tek başına) | fit | **0,80** | - | 0,69 | 0,71 | - | - |
| | holdout | 0,93 | - | 0,58 | 0,66 | - | - |
| `has_identity = 0` (koşul tek başına) | fit | 0,61 | 0,52 | 0,64 | 0,64 | 0,62 | 1,00 |
| R04 | fit | 1,25 | 2,94 (3) | 11,3 (177) | 1,84 (1.302) | 0,31 (52) | 1,70 (13.315) |
| | holdout | 1,33 | - | 7,75 (24) | 5,91 (123) | 0 (24) | 1,82 (3.504) |
| R06 | fit | 0,98 | 1,60 (271) | 8,98 (12) | 3,52 (133) | 1,80 (9) | 1,28 (7.199) |
| | holdout | 1,28 | 2,31 (68) | - | 4,75 (9) | - | 1,77 (2.017) |
| R09 | fit | 1,51 | - | 4,79 (36) | 1,07 (436) | - | - |
| | holdout | 9,84 | - | 16,9 (3) | 6,52 (59) | - | - |

Parantez içindekiler tetiklenme sayısıdır. Hücreler `eda_lift_by_product.csv` dosyasından alındı.

Bulgular (hesaplanan sayılarla):
- **Yabancı ülke etkisi büyük ölçüde ProductCD C'nin karışımından geliyor.** Fit'te yabancı addr2'li satırların %78'i (3.053/3.931) C ürünü, C'nin taban oranı da yüksek (%11,3). Genel lift 2,95 çıkıyor, ama C içinde yabancı satırlar C ortalamasından *daha az* riskli (lift 0,78, holdout 0,18). Gerçek bir yabancı ülke etkisi yalnızca küçük H ve R gruplarında görülüyor (fit 4,2 / 3,9).
- **Yeni kart (D1 = 0) etkisi ürün karışımından geliyor:** genel lift 1,18 iken ürün içi lift 0,72-1,07 (fit). R04'ün genel lift'i zayıf (fit 1,25, holdout 1,33) ve ProductCD ile karışık. R04 tetiklenmelerinin %90'ı düşük taban oranlı W ürününde; ürün içinde lift'i daha yüksek (W 1,70, R 1,84). Yani R04'teki sinyali yüksek tutar bileşeni taşıyor, ürün karışımı genel lift'i aşağı çekiyor.
- **Az işlem saati (low-volume window) etkisi her üründe tutarlı:** ürün içi lift fit'te 1,56-2,68, holdout'ta 1,37-3,29; hepsi 1'in üstünde.
- **E-posta uyuşmazlığı koşulu tek başına ters yönde:** fit lift 0,80 (holdout 0,93), H ve R içinde de 0,58-0,71. **R09 kuralı** (uyuşmazlık + yüksek tutar) ise fit'te 1,51, holdout'ta 9,84. İlk sürüm raporundaki 9,8 değeri 62 satırdan geliyor ve fit'te tekrar etmiyor. R09'u yüksek tutar bileşeni taşıyor; holdout'taki yüksek değer küçük örneklem oynaklığı olarak yorumlanmalı.
- **R06'da genel sinyal yok:** fit lift 0,98. Ancak ürün içi lift'ler 1'in üstünde (W 1,28, C 1,60, R 3,52). Tetiklenmelerin %94'ü W ürününde olduğu için genel lift 1'e iniyor. Holdout'ta genel lift 1,28.
- **R08'in kapsamı ihmal edilebilir:** fit 3, holdout 1 tetiklenme. `has_identity = 0` koşulu tek başına fit'te lift 0,61; W dışındaki ürünlerde identity'siz satır çok az.
- **R12 fit'te ters yönde** (lift 0,59, 1.300 tetiklenme); holdout'ta tetiklenmiyor.

Kurallar bu tablo nedeniyle değiştirilmedi. **Gelecek iş:** kurallar ayrı bir doğrulama dönemiyle (ör. fit'in son dilimi) kalibre edilmeli: boost, eşik ve kural seçimi orada yapılmalı, holdout yalnızca son ölçüm için kullanılmalı.

## Düzeltmeler (holdout sonucundan sonra, K-25)
İki değişiklik ilk holdout raporu görüldükten sonra yapıldı. Gerekçeleri etiketten bağımsızdır, ama yapıldıkları an nedeniyle post-hoc değişikliklerdir. Diğer kurallar (R04, R09 dahil) değiştirilmedi.
1. **R10 / kural 4 (mantık hatası):** İlk sürümde allow, skor eşiğinden gelen review'u ezebiliyordu ve düşük öncelikli bir block'a karşı kazanabiliyordu. Artık allow yalnızca kural kaynaklı, daha düşük öncelikli review'u bastırabilir (Conflict resolution, kural 4). Mevcut veride hiçbir satırın kararı değişmedi.
2. **R03 cooldown (tetiklenme yoğunlaşması):** Etiketsiz yoğunlaşma metriği, ilk sürümde R03'ün holdout tetiklenmelerinin %99,6'sının tek bir entity'den geldiğini gösterdi: patlamadaki her işlem kuralı yeniden tetikliyordu. Cooldown ile tetiklenme holdout'ta 1.128'den 21'e, fit'te 53'ten 8'e indi. Holdout'ta top-1 payı 0,904 (19/21): patlama artık saatte bir uyarı üretiyor.

## Tasarımdan sapmalar ve uyarlamalar
1. **risk_boost değerleri ve tavanı** başlangıçta tasarımda yoktu; önerilen değerler kullanıcı tarafından onaylandı (K-23): critical +0,30, high +0,15, medium +0,08, low +0,03, allow 0; toplam [-0,10, +0,40] aralığına kırpılır.
2. **"Yüksek tutar" tüm kurallarda fit q95** (tasarım R02 için q95 diyordu, diğer kurallarda aynı eşik kullanıldı). Adım 6'daki C2/C8 q90 kullanır.
3. **R03 "3 katı" yorumu:** `ent_cnt_1h / ent_daily_avg > 3`. Alternatif yorum `ent_cnt_24h / ent_daily_avg > 3` olurdu.
4. **R02/R05 "yabancı ülke"** = Adım 3'ün `foreign_addr2` feature'ı; "düşük hacim penceresi" = `is_low_volume_window` (K-06).
5. **R10'un boost'u 0:** C4 zaten x0,75 indirim veriyor; R10 yalnızca kararı etkiler.
6. **Skor tabanlı inceleme** (skill: "kural kararı + skor eşiği"): eşik boost'tan önceki skorla, fit q99 üzerinden karşılaştırılır. `decision.score_review.enabled: false` ile kapatılabilir. Allow kuralı bu incelemeyi bastıramaz (K-25).
7. **Bastırılan kuralların boost'u uygulanmaz.**
8. **Şema ekleri:** `contains` operatörü, `cooldown` alanı, boost-karar uyumu kontrolü, mesaj alanlarının yüklemede doğrulanması.
9. **Çakışma örnekleri tüm satırlardan** seçildi (holdout'ta yalnızca 1 çakışma var).
10. **`email_ent_known`** Adım 6'nın fonksiyonuyla hesaplanır (`src/rules` -> `src/context` yatay import).
11. **Cooldown online'da durumlu** (`CooldownStore`, bellek içi), çünkü "son tutulan tetiklenme" durumsuz olarak türetilemez.

## Bilinen sınırlar
- **Kurallar holdout'ta sıralamayı Adım 6'nın üstüne çıkarmıyor** (düzeltilmiş: %1'de +15, %5'te +69 FP). Ana kaynak R04 (geniş kapsam, düşük lift, ProductCD ile karışık). R01 belirgin fayda sağlıyor. Kullanıcı kararıyla R04 değiştirilmedi.
- **Az tetiklenen kurallar:** R02 (fit 1 / holdout 1), R05 (54 / 4), R08 (3 / 1), R09 (472 / 62), R11 (4 / 0). Bu kuralların precision ve lift değerleri istatistiksel olarak güvenilir değil; R09'un holdout lift'i (9,84) fit'te tekrar etmiyor (1,51).
- **R12 holdout'ta hiç tetiklenmiyor:** öğrenilen tatil sezonu (2017-12-19 ... 2017-12-26) fit dönemine düşüyor (Adım 6 C7 ile aynı durum). Fit'te ise lift 0,59.
- **R10 allow kararları ortalamadan riskli** (precision 0,106). Kart grubu entity'siyle "trusted" düşük risk anlamına gelmiyor. Allow artık skor incelemesini ve block'u ezemiyor, ama kural kaynaklı düşük öncelikli review'ları hâlâ bastırabiliyor.
- **Entity proxy:** `addr1` boş olan satırlar tek bir seviyede toplanıyor. R01 ve R10'un en yoğun entity'si bu birleşik grup (card1 15885). Bu, cooldown ve yoğunlaşma metriğini de etkiliyor.
- **Cooldown durumu bellek içi ve tek süreçli;** süreç yeniden başlarsa sıfırlanıyor. Batch'te durum boş başlıyor ve tüm veriyi zaman sırasıyla işliyor.
- **Boost değerleri elle seçildi;** sonuç bunlara duyarlı. Güven aralığı hesaplanmadı ve yalnızca tek bir holdout var.
- Kural kararı ile bütçe sıralaması ayrı kavramlar: %5 bütçedeki alarmların bir kısmı varsayılan allow kararlı (hiçbir kural tetiklenmemiş ve skor eşiğin altında). Karar eşiği fit q99, bütçe ise holdout'un %5'i.
- Varsayımlara bağlı kurallar: addr2 = 87 = ABD (R02, R05, R11), D1 = kart yaşı (R04, R12), saat dilimi/düşük hacim penceresi (R02), 3 ondalık = kur çevrimi (R11) (docs/assumptions.md).
- Online kayıt `inputs:` kataloğundaki kolonları, `email_ent_known`'u ve cooldown için `TransactionDT`, `card1`, `addr1` alanlarını taşımalı; eksik kolon `KeyError` verir.
- **Gelecek iş:** ayrı bir doğrulama dönemiyle kural kalibrasyonu (boost, eşik, kural seçimi).

## Testler (tests/rules 93 test + tests/evaluation/test_rule_metrics.py 4 test)
- Kural bazında: her kural (R01-R12) için tetiklenen ve tetiklenmeyen (sınırda) kayıt; nötr kayıt.
- Conflict resolution: öncelik, önem, karar sırası; allow ile block (block kazanır, öncelikten bağımsız); allow ile eşit/yüksek öncelikli review (review); allow ile düşük öncelikli kural review (allow); allow ile skor eşiği review (review kalır); boost tavanı; gerçek kural setiyle R02 > R04/R05 ve R04 > R10.
- Cooldown: pencere sınırı, yalnızca önceki satırlar, durum aktarımı, batch ile online sıralı yeniden oynatma eşitliği, `update_state=False`.
- Yükleme: YAML + JSON, `reload()`, geçersiz dosyada eski setin korunması, dosyalar arası yinelenen id, 11 geçersiz kural vakası, istekte gelen JSON kural seti.
- Diğer: tüm operatörler ve NaN davranışı; batch ile tek kayıt eşitliği; yoğunlaşma metriği; etiketli metrik fonksiyonları (`rule_hit_metrics`, `decision_metrics`, `budget_table`, `lift_by_group` içinde ürün karışımının ayrıştırılması); container; `src/rules` ve kural config'lerinde `isFraud` geçmemesi.

## Komutlar
- Örneklem: `SAMPLE_N=50000 python scripts/run_rules.py` (~5 sn; önce Adım 6'nın örneklem koşusu gerekir).
- Tam veri: `python scripts/run_rules.py` (~29 sn; önce `python scripts/run_context.py`).
- Pipeline içinden: `make pipeline` veya `python scripts/run_pipeline.py --only rules`.
- `--no-eval` etiketli değerlendirmeyi atlar.

Örneklem (SAMPLE_N=50000; 10.000 holdout, 228 pozitif) yalnızca duman testidir: %1'de FP 88 / 89 / 88, %5'te 468 / 456 / 468 (Adım 5 / 6 / 7). Örneklemde cooldown'a takılan satır yok. Örneklem ~2 hafta olduğu için R10 hiç tetiklenmez (yaş >= 30 gün şartı sağlanmaz).

## Bir sonraki adımın girdisi (Adım 8-9: RAG ve agent'lar)
- Online: `Container.rule_engine.evaluate(record, adjusted_score_unclipped) -> RuleEngineResult`. `explain_dict()` tetiklenen ve bastırılan kuralları (cooldown dahil), kararı, Türkçe gerekçeleri ve üç skoru verir.
- Batch: `reports/rules/rule_hits.parquet`.
- Kural açıklamaları (`description`, `message`) ve `docs/step7.md` RAG bilgi tabanına girebilir.
