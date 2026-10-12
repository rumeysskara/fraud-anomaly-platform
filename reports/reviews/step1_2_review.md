# Adım 1-2 Review (veri yükleme + profiling)

Sonuç: DÜZELTME GEREKLİ (bloklayıcı kod hatası yok; 1 anlamsal tutarsızlık, 1 eski doküman bölümü ve birkaç küçük konfigürasyon/kural sorunu)

## Kontrol tablosu

| # | Kontrol | Durum | Kanıt |
|---|---------|-------|-------|
| 1 | make test | ✅ | `36 passed in 2.89s` (-W default ile de uyarı yok) |
| 2 | make lint | ✅ | ruff `All checks passed!`; black `41 files would be left unchanged` |
| 3 | isFraud yalnızca loader/evaluation | ⚠️ | `grep -rn isFraud src scripts configs`: src/evaluation/metrics.py:1, src/data/loader.py:3 (docstring), src/profiling/entity.py:1 (docstring, "never read here"), configs/settings.yaml:14 (`label_column`). Kod olarak `isFraud` stringi profiling'de yok. Ancak `y` Series'i `src/profiling/report.py:196-199` içinde okunuyor (bkz. Bulgu 3) |
| 4 | Etiket entity/eşik/kolon seçiminde | ✅ | entity.py, schema.py, quality.py, distributions.py, relations.py `y` almıyor; `y` yalnızca `run_profile` içinde `labels` sözlüğüne (fit/holdout taban oranı) giriyor ve `summary.md` son bölümüne yazılıyor. Hiçbir seçimi etkilemiyor |
| 5 | Eşikler profiling.yaml'da tek kaynak | ⚠️ | Büyük kısmı config'den okunuyor. Kalanlar: `entity.py:72` sabit `86400.0`; `entity.py:57-59` ve `distributions.py:19` sabit yüzdelikler (25/50/75/90/99, standart, kabul edilebilir); `report.py:~160` `.head(60)`. Ayrıca D1n tanımı ve `day_seconds: 86400` hem `configs/entity.yaml` hem `configs/profiling.yaml` (entity.first_use_day, day_seconds) içinde: iki kopya (Bulgu 4) |
| 6 | Dosya alanı | ✅ | Adım 1-2 commit'i (09b468e) yalnızca src/data, src/profiling, scripts, tests, configs, docs, reports içinde. Uyarı: `docs/data_dictionary.md` takip edilmeyen (untracked) yeni dosya, bu adımın commit'inde değil |
| 7 | Katman bağımlılık yönü | ✅ | profiling -> data (`report.py:10` `add_datetime`), profiling -> core; data -> core. Ters import yok |
| 8 | Loader tek yol, imza/davranış | ✅ | `load_data(data_dir, sample_n, settings) -> (X, y)` imzası commit öncesiyle aynı; `load_data` -> `load_merged` sarmalayıcı (loader.py:128). Fark: çıktıya `has_identity` ve category dtype eklendi (step1.md'de belirtilmiş). `y` ayrı Series (loader.py:94). `validate="one_to_one"` var |
| 9 | Fit/holdout sızıntısı | ⚠️ | `holdout_seen_ratio` (entity.py:~125) yalnızca fit anahtarlarının varlığına bakıyor ve kapsama teşhisi; etiket ve holdout istatistiği öğrenmiyor, sızıntı değil. Ancak: entity karşılaştırmasının "full" kapsamı, outlier/dağılım ve özellikle Spearman/Cramér kümeleri (`redundancy_clusters`, Adım 3'te V azaltma girdisi) tüm veri (fit+holdout) üzerinden hesaplanıyor (relations.py `_sample` tüm X'ten 100k rastgele). Etiketsiz ama "istatistik fit'te öğrenilir" kuralının dışında (Bulgu 5) |
| 10 | entity.yaml ve K-05 tutarlılığı | ⚠️ | entity.yaml:11-16, decisions.md K-05, step2.md "Bir sonraki adımın girdisi" hepsi aynı: kart yaşı = D1, D1n = floor(TransactionDT/86400) - D1. Ayrım iç tutarlı. Ama veri bu tanımı desteklemiyor (Bulgu 2) |
| 11 | docs/step1.md, step2.md | ⚠️ | Her ikisinde "isFraud kullanımı: hayır" notu, çıktı/şema/sonraki girdi/sınırlar var. step2.md'de eski "Entity kararı (bekliyor)" bölümü duruyor (Bulgu 1). Sayılar CSV ile doğrulandı: H tanımsız 0, 39.974 entity, holdout görülme 0,9578, I 217.850 / 0,435, D1n sabitlik %53,8/%46,0, negatif D sayıları, taban oranları 0,0351/0,0344 |
| 12 | Kişisel çalışma notları | ✅ | kişisel çalışma notları .gitignore'da (repo dışı); takipte değil |
| 13 | Her modül için pytest, gerçek veriye bağımlılık | ✅ | 36 test; loader (tests/core, tests/data), schema/quality, distributions/relations, entity/report (figures dahil, tmp_path ve sentetik veri). tests altında data/raw veya gerçek CSV referansı yok. `config.py` için ayrı test yok (dolaylı kapsanıyor, önemsiz) |
| 14 | run_pipeline.py entegrasyonu | ✅ | `STEPS["profile"] = scripts/run_profiling.py` (var); `make profile` -> `--only profile`; olmayan adımlar "skip" ile atlanıyor (`--only features` çıktısı doğrulandı) |
| 15 | reports/ tutarlılığı | ✅ | Tam veri ve sample çıktıları ayrı dizinlerde (reports/profile, reports/profile/sample); csv'ler commit'li, parquet'ler `.gitignore` (`*.parquet`) kapsamında |
| 16 | Örneklem -> tam veri, süre/bellek | ✅ | step1.md: SAMPLE_N=50000 ~26 s / 1,5 GB; tam ~82 s / ~3,5 GB. Hem `reports/profile/` hem `sample/` çıktısı mevcut |

## Case maddeleri
- Adım 1: join (LEFT, one_to_one, has_identity) ✅; eksik veri (missing/group_missing/null_block) ✅; otomatik kolon tipi (kural tabanlı, card/addr istisnası belgeli) ✅; veri kalitesi (quality_checks) ✅; dağılım ✅; yüksek cardinality ✅
- Adım 2: numeric/categorical/datetime ✅; null ratio ✅; outlier (IQR + robust z) ✅; distribution ✅; rare combination ✅; kolon ilişkileri ✅; entity pattern ✅

## Bulgular (önem sırasına göre)

1. DÜZELTME (doküman): `docs/step2.md` içinde "## Entity kararı (bekliyor) ... karar ana oturumda kullanıcıya sorulacak" bölümü duruyor; aynı dosyada "H seçildi (K-05)" yazıyor. Eski bölüm silinmeli.

2. DÜZELTME (anlamsal, kullanıcıya sorulmalı): K-05 ve entity.yaml "kart yaşı = D1 (ilk kullanımdan bu yana gün)" diyor. Kendi bulgumuz bunu zayıflatıyor: `reports/profile/d1n_constancy.csv`, sıkı kart anahtarı REF (card1..card6+addr1) için işlemlerin ~%95,8'inde D1n aralığı > 1 gün (medyan 160 gün). D1 gerçekten "ilk kullanımdan beri gün" olsaydı D1n kart başına sabit olurdu. step2.md bunu "H birden çok kartı birleştiriyor" diye yorumluyor, ama REF anahtarında da aynı sonuç çıkması bu açıklamayı zayıflatıyor; D1'in "önceki işlemden bu yana gün" (data_dictionary.md:21 ilk ifade) olma ihtimali daha güçlü. Öneri: K-05/entity.yaml/step2'de "kart yaşı" ifadesini "varsayım, veriyle doğrulanamadı/çelişiyor" olarak yumuşatmak veya Adım 3'te D1'i "son işlemden beri gün" olarak adlandırmak. Bu bir iş kuralı kararı olduğundan seçim kullanıcıya ait; ben değiştirmedim. Not: step2.md "D1n gürültülü değil, ayırt edici" cümlesi de bu bağlamda fazla kesin.

3. UYARI (kural yorumu): `src/profiling/report.py:196-199` `y.iloc[:cut].mean()` ile etiket okuyor; kurallar `isFraud` okumasını yalnızca loader ve `src/evaluation/` ile sınırlıyor. Seçimleri etkilemiyor ve dokümante, ama kural harfiyen ihlal sayılabilir. Seçenekler: (a) olduğu gibi bırak, istisnayı step docs'ta belirt (şu an belirtilmiş); (b) taban oranı hesabını `src/evaluation/metrics.py` içine taşı, `run_profile` `y` almasın (öneri: b, daha temiz savunulur).

4. UYARI (tek kaynak): D1n tanımı ve `day_seconds: 86400` iki dosyada (`configs/entity.yaml`, `configs/profiling.yaml` `entity.first_use_day`/`day_seconds`); profiling hiçbir zaman entity.yaml'ı okumuyor, sapma riski var. Ayrıca `entity.py:72` `/ 86400.0` sabit; `day_seconds` config'ten alınmalı. profiling.yaml'daki "Reference for the D1n constancy check" yorumu REF adayının ortasına yanlış girintiyle düşmüş (okunabilirlik).

5. UYARI (fit/holdout): Spearman/Cramér kümeleri, outlier ve dağılımlar tüm veri üzerinden; küme çıktısı Adım 3'te V azaltma için kullanılacak. Etiket yok, ama holdout yapısı seçime sızıyor. Seçenekler: (a) kabul et ve step2.md "Bilinen sınırlar"a açıkça yaz (şu an yalnızca "split değildir" diyor, holdout'u içerdiğini söylemiyor); (b) ilişki/küme analizini fit kümesinde (`X.iloc[:cut]`) çalıştır. Öneri: (b), maliyeti düşük.

6. KÜÇÜK: `docs/data_dictionary.md` untracked; commit edilecekse step doc'una bağlanmalı. `reports/profile/*.parquet` ignore olduğundan, step docs'ta "Adım 3 `column_schema.parquet` okur" yazıyor; temiz klonda dosya yok (csv var). Adım 3 girdisi olarak pipeline'ın önce `profile` çalıştırdığı ya da csv okunacağı not edilmeli.

7. KÜÇÜK: `entity.yaml` şu an hiçbir kod/test tarafından okunmuyor (Adım 3 yazacak); Adım 3'te şema testi eklenmeli.

## Düzeltilmesi gerekenler (kısa liste)
- step2.md: "Entity kararı (bekliyor)" bölümünü sil (Bulgu 1)
- D1 "kart yaşı" yorumunu karar/doküman düzeyinde gözden geçir; kullanıcı karar versin (Bulgu 2)
- Taban oranını src/evaluation'a taşı veya istisnayı kabul et (Bulgu 3)
- 86400 sabitini ve D1n tanımının çift kopyasını tek kaynağa indir (Bulgu 4)
- İlişki kümelerini fit kümesinde hesapla veya sınırı dokümante et (Bulgu 5)

## Kullanıcının karar vermesi gerekenler
- Bulgu 2: D1 yorumu (kart yaşı mı, önceki işlemden beri gün mü); K-05 metninin güncellenmesi
- Bulgu 3: Taban oranı raporlaması (a) loader/profiling'de kalsın, (b) evaluation'a taşınsın
- Bulgu 5: İlişki analizi (a) tüm veri + not, (b) yalnızca fit
