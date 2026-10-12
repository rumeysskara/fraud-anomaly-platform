# Adım 6 (Context Adjust) ve Adım 7 (Rule Engine) - Bağımsız Denetim

Tarih: 2026-10-12. HEAD: `de7625a`. Denetçi kod değiştirmedi; yalnızca komut çalıştırdı ve dosya okudu.
Not: görevde istenen yol `reports/review/` idi. Yazma alanım `reports/reviews/` olduğu için rapor buraya yazıldı.

## Özet

| Adım | Sonuç | Gerekçe |
|---|---|---|
| Adım 6 - Context Adjust | **GEÇTİ** | Testler/lint yeşil, sızıntı yok, case maddeleri (business hours, weekend, trusted entity, kendi kuralları, önce/sonra FP) karşılanıyor, doküman sayıları raporlarla tutarlı. Yalnızca küçük bulgular var. |
| Adım 7 - Rule Engine | **KOŞULLU** | Case maddelerinin tamamı karşılanıyor, sayılar tutarlı. Kritik bulgu yok. 4 önemli bulgu var: bugünkü kural setinde etkisi olmayan bir resolver uç durumu, CooldownStore'un container'a bağlanmaması, online `evaluate()`'in varsayılan olarak durum değiştirmesi (API'de aynı kayıt iki kez sorgulanırsa farklı sonuç verir), decisions.md'de K-22'nin eskimiş olması. |

**Sonuç: DÜZELTME GEREKLİ** (yalnızca Adım 7 için, küçük kapsamlı; Adım 6 olduğu gibi kabul edilebilir).

---

## 1. Testler ve lint

| Kontrol | Durum | Kanıt |
|---|---|---|
| `make test` | ✅ | `250 passed in 21.08s` |
| `make lint` | ✅ | `ruff check src tests scripts` -> `All checks passed!`; `black --check` -> `129 files would be left unchanged.` |
| Adım 6/7 alt kümesi | ✅ | `pytest tests/rules tests/context tests/evaluation` -> `139 passed`. Toplanan testler: tests/rules 93, tests/context 38, test_rule_metrics 4. Bu sayılar step7.md:40 ve step6.md:258 ile aynı. |

## 2. Leakage

### 2a. `isFraud` grep (`grep -rn isFraud src scripts configs tests`)
| Konum | Tür | Değerlendirme |
|---|---|---|
| `src/data/loader.py:3` (docstring), `:78`, `:105` (`y = df.pop(label_col)`) | izinli gerçek kullanım | ✅ Kurala uygun |
| `src/evaluation/metrics.py:1` | docstring | ✅ |
| `src/profiling/entity.py:1` | docstring ("isFraud is never read here") | ✅ Kullanım değil, ihlal yok |
| `configs/settings.yaml:14` `label_column: isFraud` | config değeri | ✅ Yalnızca `src/data/loader.py:78` okuyor (`grep label_column src scripts` başka sonuç vermedi). Kolon adının tek yerde tutulması doğru tasarım. |
| `configs/weights.yaml:2` | yorum | ✅ |
| `configs/context.yaml:21` | yorum | ✅ Ayrıca `ContextAdjustEngine._check_config` (src/context/engine.py:97-107) bilinmeyen kolonu reddediyor, yani `isFraud` koşulda kullanılamaz. |
| `scripts/` | hiç geçmiyor | ✅ |
| `tests/*` | negatif testler ve sentetik loader verisi | ✅ (`tests/rules/test_repository.py:72`, `isFraud` koşulunun "unknown feature" ile reddedildiğini test ediyor) |

Sonuç: dört dosyadaki geçişlerin hiçbiri ihlal değil. Skill'in "başka yerde varsa KIRMIZI" kuralı düz grep eşleşmesi içindir; buradaki eşleşmeler yorum, docstring ya da loader'ın okuduğu config değeri. İsteğe bağlı: yorumlardaki kelime "the label" olarak değiştirilirse grep temiz çıkar (küçük, kozmetik).

### 2b. Etiketin script içinde kullanımı
- `scripts/run_rules.py:177-260`: `y` loader'dan geliyor ve `src/evaluation/rule_metrics.py` fonksiyonlarına veriliyor. Yalnızca log ve `holdout_base.csv` için `y_hold.sum()` / `y_hold.mean()` (satır 199, 232-233) script içinde hesaplanıyor. ⚠️ küçük
- `scripts/run_context.py:81-135`: `evaluate_holdout()` içinde `tp = alarms - fp`, `y_hold.sum()` script'te hesaplanıyor. Adım 7'de etiketli hesaplar `src/evaluation`'a taşındı, Adım 6 script'i taşınmadı. ⚠️ küçük (bkz. K6-2)

### 2c. Zamansal özellikler (yalnızca geçmiş mi?)
| Özellik | Durum | Kanıt |
|---|---|---|
| R01 `small_amt_streak_1h` | ✅ geçmiş | `src/features/history.py:136-141`: `idx - lo` sayımı mevcut satırı içermiyor (sıralı anahtarda `searchsorted(..., side="left")`, `cum_small[idx] - cum_small[lo]`). Test: `tests/features/test_no_leakage.py:51-71` (`[0,1,1,1,0]`), ayrıca gelecek satır testi (`:24`) ve ilk işlem testi (`:9`). |
| `ent_cnt_1h`, `ent_txn_count`, `ent_avg_amt`, `amt_ratio_to_ent_avg` | ✅ geçmiş | Aynı fonksiyon. `cumcount` ve `shift(1)`: history.py:98-105. |
| `email_ent_known` | ✅ geçmiş | `src/context/inputs.py:28-33`: TransactionDT'ye göre stable sıralama + `cumcount() >= 1`. Test: tests/context (step6.md:259). |
| `ent_daily_avg`, `burst_ratio_1h`, `known_*` | ✅ geçmiş | `src/rules/derive.py:28-43` yalnızca yukarıdaki geçmiş kolonlardan türetiyor. |
| R03 cooldown | ✅ geçmiş | `src/rules/cooldown.py:19-40`: satırlar zaman sırasıyla geziliyor, yalnızca önceki *tutulan* tetiklenmeye bakılıyor. Testler: `tests/rules/test_cooldown.py:20` (`test_apply_cooldown_uses_only_earlier_rows`), `:52` (batch = online sıralı yeniden oynatma). |
| Not | ⚠️ küçük | Aynı `TransactionDT` değerini paylaşan satırlarda sıralamada önce gelen satır "geçmiş" sayılıyor (stable sıralama). Adım 3 ile tutarlı; dokümanda tek cümleyle belirtilebilir. |

### 2d. Eşikler fit kümesinden mi öğreniliyor?
| Parametre | Durum | Kanıt |
|---|---|---|
| `amount_small` q10, `amount_high` q95, `velocity_1h_extreme` q99.9, `score_review_threshold` q99 | ✅ | `src/rules/params.py:20-27` `fit_params(fit_df)`. Çağrı: `scripts/run_rules.py:281-282`, `fit_frame = inputs.loc[parts["fit"]]` (`split_by_time`, TransactionDT'ye göre %80). Değerler `configs/rules.yaml:297-302` ve `reports/rules/rule_params.json` içinde aynı (25.95 / 441.95 / 12 / 1.0696, n_fit 472432). |
| `trusted_min_history` (809) | ✅ | Adım 6 artifact'ından okunuyor (`params.py:30-40`); Adım 6'da fit q90 (`src/context/params.py`). |
| Adım 6 `amount_high` q90 = 277, `dominant_addr2` = 87 | ✅ | `ContextParams.fit` yalnızca fit satırlarıyla (step6.md:53, `scripts/run_context.py:167-176`). |

## 3. Case gereksinimleri

### Adım 6
| Madde | Durum | Kanıt |
|---|---|---|
| Business hours | ✅ | C1, `configs/context.yaml`; step6.md:60 |
| Weekend | ✅ | C3; step6.md:62 |
| Trusted entity | ✅ | C4 (revize, K-20a); step6.md:64, 160-180 |
| Kendi kuralları (en az 6, gerekçeli) | ✅ | C2, C5-C9, G1 koruması; `rationale` alanı config'te |
| Parametreler config'te, fit'ten öğreniliyor | ✅ | `configs/context.yaml`, `artifacts/context/context_params.json` |
| Önce/sonra FP metriği | ✅ | `reports/context/fp_comparison.csv` = step6.md:184-194 (995 / 1040 / 983; 5222 / 5291 / 5068) |
| Batch = online | ✅ | `adjust_batch` ve `adjust_one` aynı `_core` fonksiyonunu kullanıyor (engine.py:1-7); 300 satırlık eşitlik testi |
| Container | ✅ | `src/container.py:31` |

### Adım 7
| Madde | Durum | Kanıt |
|---|---|---|
| 8-10+ kural | ✅ | 12 kural: R01-R10 `configs/rules.yaml`, R11-R12 `configs/rules_extra.json` |
| YAML + JSON | ✅ | `configs/rules.yaml:32` `files.rules: [rules.yaml, rules_extra.json]`; `repository.py:92-96`; test `test_yaml_and_json_rules_are_loaded` |
| pydantic doğrulama | ✅ | `src/rules/schema.py` (`extra="forbid"`, Literal tipler, op-değer uyumu, boost-karar uyumu); `repository.py:134-158` (yinelenen id, bilinmeyen feature/param/şablon alanı); 11 geçersiz kural testi |
| Priority | ✅ | `resolver.py:36-43` sort_key |
| Conflict resolution: priority > severity > block>review>allow | ✅ | `resolver.py:36-43`; testler `test_priority_wins`, `test_severity_breaks_priority_tie`, `test_decision_order_breaks_full_tie` |
| allow yalnızca kural kaynaklı, daha düşük öncelikli review'u bastırır | ✅ (uç durum hariç, bkz. K7-1) | `resolver.py:49-55`; testler `test_allow_never_overrides_block`, `test_allow_suppressed_by_higher_or_equal_priority_risk`, `test_allow_overrides_lower_priority_rule_review` |
| Skor eşiği review'u allow bastıramaz; skor eşiği block/review'u bastırmaz | ✅ | `engine.py:180-198`: eşik yalnızca kararsız (`undecided`) satırlara ve allow satırlarına uygulanıyor. Test `test_allow_cannot_override_score_review` |
| Bastırılanlar nedenleriyle | ✅ | `resolver.py:58-77` (Türkçe neden), cooldown nedeni `engine.py:32, 295-303` |
| Explainability (triggered, suppressed, final_decision, Türkçe reasons gerçek değerlerle, 3 skor) | ✅ | `RuleEngineResult.explain_dict` (`engine.py:51-67`); `reports/rules/conflict_examples.json` (ör. "Kart testi şüphesi: 22.91 USD ... son 1 saatte 16 önceki küçük işlem") |
| final = adjusted + tavanlı boost | ✅ | `resolver.py:92-99` (clip [-0.10, 0.40]), `engine.py:172-174` |
| Sıralama kırpılmamış skorla | ✅ | `scripts/run_rules.py:206-213` `final_score_unclipped` + `tie_break_order` |
| RuleRepository YAML+JSON + `reload()` | ✅ | `repository.py:113-123`; geçersiz dosyada önceki set korunuyor (doğrulama, atamadan önce yapılıyor: satır 120-121); test `test_invalid_file_keeps_previous_set` |
| `evaluate(record, score, rules=None)` istekte gelen kural seti doğrulaması | ✅ | `engine.py:240-242` -> `repository.parse` -> `validate_rules`; testler `test_request_time_rule_set_json_text`, `test_request_time_rule_set_is_validated` |

## 4. Batch / online ve DI

| Kontrol | Durum | Kanıt |
|---|---|---|
| Aynı kod | ✅ | `evaluate_batch` ve `evaluate` ikisi de `add_derived -> hit_matrix -> apply_cooldowns -> decide` çağırıyor (`engine.py:205-258`). Script 250 satırı (cooldown'a takılan 50 satır dahil) iki yoldan çalıştırıp karşılaştırıyor (`run_rules.py:303-312`, fark 0). Test `test_batch_equals_single_record`. |
| Global state yok | ✅ | Durum `RuleEngine` örneğinin içinde tutuluyor, modül seviyesinde değişken yok. Container Singleton. |
| CooldownStore container'dan inject ediliyor mu | ⚠️ önemli (K7-2) | `engine.py:82`: store verilmezse `CooldownStore()` sınıfın içinde oluşturuluyor. `src/rules/factory.py:16` ve `src/container.py:36` store geçirmiyor. Kural: "Servis içinde bağımlılık new ile oluşturulmaz; constructor ile enjekte edilir" (.claude/rules/architecture-di.md). |
| Online durum davranışı | ⚠️ önemli (K7-3) | Aşağıda. |

## 5. Mimari

| Kontrol | Durum | Kanıt |
|---|---|---|
| Ters yönde import yok | ✅ | `grep "from src.(api|agents|evaluation|rag)" src/rules src/context src/scoring src/features src/data` boş. `src/context`, `src/scoring` ve `src/features` içinde `from src.rules` yok, yani döngü yok. |
| `src/rules -> src/context` yatay import (`email_known_batch`, `RAW_SOURCE_COLUMNS`, `EMAIL_KNOWN`) | ⚠️ küçük, kabul edilebilir | `src/rules/derive.py:15-16`. Mimari kuralında rules ve context aynı katmanda; döngü yok ve step7.md:369'da belgelenmiş. Daha temiz çözüm: `email_known_batch` bir geçmiş feature'ı olduğu için `src/features/` altına taşınabilir, rules ve context oradan okur. Benzer şekilde `src/context/engine.py:23` ve `factory.py:13` `src/scoring`'den import ediyor (aynı katman). |
| interfaces.py / container.py yalnızca ekleme | ✅ | Adım 6-7 commit'lerinde `git diff <c>~1 <c> -- src/container.py src/core/interfaces.py`: yalnızca `+` satırlar (200cc21: container +4; 34171d8: container +7, interfaces +12 `RuleStore`). Silinen satır yok. |
| Arayüz uyumu | ✅ | `RuleEngine(RuleEvaluator)`; `evaluate` imzası ek isteğe bağlı parametrelerle geriye uyumlu. `RuleRepository(RuleStore)`. `ContextAdjustEngine(ContextAdjuster)`. |

## 6. Testler

| Kapsam | Durum | Kanıt |
|---|---|---|
| Her kural için tetiklenen / tetiklenmeyen | ✅ | `tests/rules/test_rules.py:73-89` (`test_every_loaded_rule_has_a_case` yeni bir kural eklenince testin zorunlu olmasını sağlıyor) |
| Conflict | ✅ | `tests/rules/test_resolver.py` (16 test) |
| JSON yükleme, reload | ✅ | `test_repository.py:38-52, 90-96` |
| İstekte gelen kural seti | ✅ | `test_repository.py:104-115` |
| Cooldown | ✅ | `test_cooldown.py` (5 test) |
| Evaluation fonksiyonları | ✅ | `tests/evaluation/test_rule_metrics.py` (4 test) |
| Sentetik veri, gerçek veriye bağlı değil | ✅ | Fixture'lar elle yazılmış dict'ler; `PARAMS` sabit (`tests/rules/conftest.py:13-19`). Testler `configs/rules.yaml` dosyasını okuyor (veri değil, config). |
| Eksik test | ⚠️ | K7-1'deki uç durum (allow kazanır, sonra skor eşiği onu bastırır, düşük öncelikli kural review'u hâlâ bastırılmış görünür) için test yok. |

## 7. Doküman

| Kontrol | Durum | Kanıt |
|---|---|---|
| isFraud notu | ✅ | step6.md:3, step7.md:3 |
| Kural tablosu | ✅ | step6.md:58-74, step7.md:101-114 |
| Conflict algoritması | ✅ | step7.md:152-184 |
| Örnek JSON çıktı | ✅ | step7.md:194-222, `conflict_examples.json` ile aynı |
| Üç satırlı tablo (Adım 6 / 7 ilk / 7 düzeltilmiş) | ✅ | step7.md:267-279; `budget_comparison.csv` ve `v1/budget_comparison.csv` ile aynı (998/998, 5253/5137, PR-AUC 0.0785/0.0822) |
| EDA tutarlılık kontrolü + "kural seçiminde kullanılmadı" | ✅ | step7.md:301-302 |
| Bilinen sınırlar (R12, az tetiklenen kurallar, entity proxy) | ✅ | step7.md:372-383 |
| Süre / bellek notu | ⚠️ küçük | Süreler var (Adım 6 ~16 sn, Adım 7 ~29 sn), bellek notu yok. |
| decisions.md K-23, K-25 | ✅ | decisions.md:143, 155 |

**Sayı çapraz kontrolü (hepsi tutarlı):**
- holdout 118.108 / 4.064 / %3,44 = `rules/holdout_base.csv`
- Karar metrikleri block 1.130 / 148 / 982, review 5.147 / 339 / 4.808, allow 111.831 = `decision_metrics.csv`. Toplam 118.108. Review = 4.514 kural + 633 skor = `decision_distribution.csv`
- v1 review 6.254 / FP 5.915 = `v1/decision_metrics.csv`
- R03: tetiklenme 1.128 -> 21 (holdout), 53 -> 8 (fit), top-1 payı 0,9048 = `rule_coverage.csv`
- R09 holdout lift 9,84, fit 1,51; R06 fit lift 0,978; R12 fit 0,59 = `eda_fit_vs_holdout.csv`
- R04 tetiklenmelerinin %90'ı W: 13.315 / 14.849 = %89,7
- Ablation: R01 çıkarılınca FP@%1 1.051, R04 çıkarılınca PR-AUC 0,0870 = `rule_ablation.csv`
- Boost etkisi: 5.644 satır, ort. 0,1926, tavana takılan 0 (fit 6) = `score_effect.csv`
- Adım 6: C4 kapsaması %2,05 / %3,98 = `c4_coverage.csv`; üç satırlı tablo = `fp_comparison.csv`

## 8. notes/
| Kontrol | Durum | Kanıt |
|---|---|---|
| `notes/step7_interview.md` var | ✅ | dosya mevcut |
| gitignore'da | ✅ | `git check-ignore -v` -> `.gitignore:16:notes/`; `git ls-files notes` -> 0; `git log --all -- notes` boş |
| step6/7.md'ye sızma | ✅ | `grep -i "görüşme\|interview\|soru-cevap\|nasıl anlatırım" docs/step6.md docs/step7.md` boş |

## 9. Kod sadeliği ve standartlar
- Type hint: AST taraması (src/rules, src/context, src/evaluation/rule_metrics.py): public fonksiyonların hepsinde dönüş tipi var. ✅
- Docstring: tek eksik `src/rules/explain.py:31` `_Formatter.format_field` (özel sınıfta override, kabul edilebilir). `scripts/run_rules.py:146` `OnlineReplay.evaluate` dönüş tipi yok (`# noqa: ANN201`). ⚠️ küçük
- Dosya boyutu < 400 satır: en büyükleri `src/rules/engine.py` 335, `scripts/run_rules.py` 321. ✅
- Sihirli sayı: eşikler ve boost'lar config'te. `resolver.py` sıralama tabloları algoritmanın parçası (schema.py:14 notu). ✅
- Okunabilirlik: modüller tek sorumluluklu (schema / conditions / resolver / cooldown / explain / engine). `decide()` (engine.py:144-202) skor eşiğinden sonra listeleri yeniden yazdığı için en zor okunan kısım. K7-1 düzeltmesi burayı sadeleştirmek için de bir fırsat.

---

## Bulgular (önem sırasıyla)

### Kritik
Yok.

### Önemli

**K7-1. Allow kuralı skor eşiği tarafından bastırılınca, onun bastırdığı düşük öncelikli kural review'ları bastırılmış kalıyor.**
`src/rules/engine.py:183-197` + `src/rules/resolver.py:49-55`. Kanıt (scratchpad'de istek anında verilen kural setiyle çalıştırıldı, kod değiştirilmedi): A1 (p1, allow) + V5 (p5, review), skor 0,95, eşik 0,90 ->
```
final_decision: review, decision_source: score, applied_rules: [],
suppressed: V5 "A1 kazandı (öncelik 1, low, allow): daha yüksek öncelik (1 < 5)",
            A1 "allow kuralı, skor eşiğinden gelen review kararını bastıramaz",
reasons: ["Karar kuralı tetiklenmedi; skor 0.950 ..."], boost_total: 0.0
```
Karar doğru (review), ama: (i) V5 kazanmış sayılması gereken allow'a yenildiği gerekçesiyle bastırılmış görünüyor; (ii) V5'in +0,08 boost'u uygulanmıyor; (iii) "Karar kuralı tetiklenmedi" ifadesi yanlış, çünkü iki kural tetiklendi. **Bugünkü kural setinde bu durum oluşmuyor**: R10 p5 ile en düşük öncelikte, yani `allows[0].priority < risk[0].priority` hiç sağlanmıyor. Ama istek anında verilen kural setlerinde ve gelecekte config değişirse oluşabilir. `/rules/evaluate` endpoint'i (Adım 10) bu yolu açacak.
*Öneri:* skor eşiği allow'u bastırdığında çözümü allow kuralları olmadan yeniden çalıştırmak (`resolve([r for r in triggered if decision != "allow"])`). Böylece kural review'ları uygulanır ve `decision_source` kural id'si olur. Allow'un skor nedeniyle bastırıldığı nedeni korunur. Bu uç durum için bir test eklenmeli. Seçim kullanıcıya ait (aşağıda).

**K7-2. CooldownStore container'dan inject edilmiyor.**
`src/rules/engine.py:82` (`CooldownStore()` sınıf içinde oluşturuluyor), `src/rules/factory.py:12-16`, `src/container.py:36`. architecture-di.md kuralı: bağımlılık constructor ile enjekte edilir, testte `override` edilir. Constructor parametresi zaten var. Eksik olan yalnızca bağlantı.
*Öneri (ekleme):* `cooldown_store = providers.Singleton(CooldownStore)`; `rule_engine = providers.Singleton(load_rule_engine, rule_repository, cooldown_store=cooldown_store)`; `load_rule_engine` parametreyi `RuleEngine`'e geçirir. İleride Redis tabanlı bir store da aynı noktadan değiştirilebilir.

**K7-3. Online `evaluate()` varsayılan olarak durumu değiştiriyor (`update_state=True`), bu yüzden aynı kaydın ikinci değerlendirmesi farklı sonuç veriyor.**
`src/rules/engine.py:229, 255`. Kanıt: cooldown'lu bir kural ve aynı kayıt iki kez -> `review`, sonra `allow` (ikinci çağrıda "cooldown: ... zaten tetiklendi"). Adım 10'da `/score` ve `/explain` aynı işlemi sorgularsa ya da istemci isteği tekrar gönderirse karar değişir. Ayrıca istek anında verilen kural setleri de paylaşılan store'a yazıyor ve durum yalnızca rule id ile tutuluyor (`cooldown.py:54-56`). Bu yüzden istekte gönderilen "R03" adlı bir kural, yüklü R03'ün durumunu değiştirir.
*Öneri:* (a) istek anında verilen kural setlerinde durumu her zaman salt okunur kullanmak (`rules is not None` ise `update_state=False`); (b) aynı TransactionID ikinci kez gelirse durumu güncellememek (idempotency anahtarı); (c) bu davranışı step7.md "Bilinen sınırlar" bölümüne ve API girdisine not olarak eklemek. Adım 10'dan önce karar verilmeli.

**K7-4. decisions.md K-22, K-25 ile çelişiyor ve "değişti" olarak işaretlenmemiş.**
`docs/decisions.md:138-141`: "Allow kuralı skor tabanlı incelemeye üstün gelir" ve "allow yalnızca eşit veya daha yüksek öncelikli bir block/review yoksa geçerli". K-25(1) bunların ikisini de değiştirdi. K-18'deki "(DÜZELTİLDİ)" yöntemiyle K-22 başlığına "(K-25 ile değişti)" eklenmeli ve eski cümlelere işaret konmalı. Aynı eski tanım `configs/rules.yaml:25-26`'daki yorumda da duruyor (block'un öncelikten bağımsız kazandığı yazmıyor). `configs/rules.yaml:42` "review if final_score_unclipped >=" diyor; kod ise boost öncesi `adjusted_score_unclipped` ile karşılaştırıyor (engine.py:183, step7.md:164 doğru). Kullanıcı görüşmede K-22'yi okursa yanlış kuralı anlatır.

### Küçük

- **K7-5.** `resolver.py:64-65`: block tetiklendiği halde kazanan bir review olduğunda (ör. V1 p1 review + B3 p3 block + A2 allow), allow'un nedeni "allow kuralı block kararını hiçbir zaman bastıramaz (tetiklenen block var)" oluyor. Oysa allow'u yenen p1 review. Kanıt scratchpad çıktısında. Öneri: nedeni kazanan kuralın kararına göre seçmek.
- **K7-6.** `RuleEngine.params` oluşturma anında sabitleniyor (`engine.py:80`). `repository.reload()` yeni bir `learned_params` tanımını kabul eder (param adı doğrulaması settings üzerinden yapılıyor), ama motor bu değeri bilmez ve değerlendirme sırasında `KeyError` oluşur. Öneri: reload'da parametreleri de yeniden okumak ya da `validate_rules`'ı `engine.params` ile de çalıştırmak.
- **K7-7.** `src/context/inputs.py:18` `RAW_SOURCE_COLUMNS` içine `card1`, `addr1` sabit yazılmış. `email_known_batch` ise entity kolonlarını `entity.yaml`'dan okuyor. Entity proxy değişirse batch girdisinde `KeyError` oluşur. Öneri: kolonları entity.yaml'dan türetmek.
- **K7-8.** `scripts/run_rules.py:199, 232-233` `y_hold.sum()`/`mean()`; `src/evaluation/base_rate.py` mevcut, oradan kullanılabilir. `scripts/run_rules.py:146` dönüş tipi eksik (`-> RuleEngineResult`). `OnlineReplay.evaluate` `engine.cooldown_store` alanını dışarıdan yeniden atıyor (satır 151). Script için kabul edilebilir, ama K7-2 ile birlikte store bir parametre olarak verilebilir.
- **K7-9.** Aynı `TransactionDT` değerine sahip satırlarda "geçmiş" tanımı stable sıraya bağlı (cooldown, email_ent_known, pencere sayıları). step7.md "Cooldown" bölümüne tek cümlelik not eklenebilir.
- **K7-10.** step7.md "Komutlar": bellek notu yok (skill kontrol 8).

### Adım 6'ya özel küçük bulgular
- **K6-1.** `docs/step6.md:72-74`: C9 notu paragrafı tablonun ortasında. Bu yüzden G1 satırı başlıksız bir tablo satırı olarak kalıyor ve markdown'da bozuk görünüyor. G1 satırı nottan önceye taşınmalı.
- **K6-2.** `scripts/run_context.py:81-135`: etiketli hesap (`tp = alarms - fp`, `y_hold.sum()`) script içinde. Adım 7'de olduğu gibi `src/evaluation` içine bir `fp_impact_table(y, scores, budgets)` fonksiyonu olarak taşınabilir. Sonuç değişmez, kural metniyle (data-leakage.md) birebir uyum sağlanır.
- **K6-3.** `docs/step6.md:58-73`: tablo "pay sütunları ilk tasarımın koşusudur" diyor, ama C4 (revize) satırı revize değerleri gösteriyor ve C9a %11,9 ilk tasarıma ait (revize `rule_coverage.csv`: %1,09 fit / %0,94 holdout). Revize paylar için ayrı bir sütun eklenirse karışıklık giderilir.
- **K6-4.** Bellek notu yok (skill kontrol 8).

---

## Düzeltilmesi gerekenlerin kısa listesi
1. (K7-1) Skor eşiği allow'u bastırdığında çözümü allow kuralları olmadan yeniden çalıştır ve bu durum için test ekle. **Kullanıcı kararı gerekli.**
2. (K7-2) `CooldownStore` için container provider ekle ve `load_rule_engine`'e geçir (container.py'ye yalnızca ekleme).
3. (K7-3) Online durum politikası (istek anında verilen kural setlerinde salt okunur, idempotency) için karar ver ve dokümana ekle. **Kullanıcı kararı gerekli.**
4. (K7-4) decisions.md K-22'yi "K-25 ile değişti" olarak işaretle; `configs/rules.yaml:25-26, 42` yorumlarını koda göre güncelle.
5. Küçükler (K7-5..K7-10, K6-1..K6-4): isteğe bağlı, tek commit'te toplanabilir.

## Kullanıcının karar vermesi gerekenler
- **K7-1 politikası:**
  (a) Allow kurallarını çıkarıp yeniden çöz. Kural review'ları ve boost'ları uygulanır, kaynak kural id'si olur. Öneri bu; açıklama tutarlı olur ve "allow bastırıldıysa onun etkisi tamamen geri alınır" ilkesine uyar.
  (b) Kararı skor kaynaklı bırak, ama düşük öncelikli review'ları "applied" yap ve boost'larını uygula (karışık kaynak, açıklaması daha zor).
  (c) Değiştirme, yalnızca dokümana yaz (bugünkü config'te etkisi yok, ama `/rules/evaluate` ile açığa çıkar).
- **K7-3 politikası:**
  (a) İstek anında verilen kural setlerinde durum her zaman salt okunur kullanılır, yüklü set güncellenir. Öneri bu; basit ve güvenli.
  (b) TransactionID tabanlı idempotency (aynı işlem durumu bir kez günceller; ek bellek ister).
  (c) Varsayılanı `update_state=False` yap, durumu yalnızca `/score` gibi "işlemi kaydeden" endpoint güncellesin.

## Açık konular
- Adım 7 kuralları holdout'ta Adım 6'nın sıralamasını iyileştirmiyor (+15 / +69 FP). Belgelenmiş ve kullanıcı kararıyla kabul edilmiş (K-24, K-25). Denetim açısından engel değil.
- `reports/review/` ile `reports/reviews/` yol farkı: rapor yazma alanı içindeki `reports/reviews/step6_7_review.md` dosyasına yazıldı.
