# Karar Kayıtları

Her önemli karar için: Karar / Alternatifler / Neden seçildi.
Kararları geliştirici verir; Claude Code seçenekleri sunar.

## Şablon

### K-XX: <başlık>
- **Karar:**
- **Alternatifler:**
- **Neden seçildi:**

## Kayıtlar

### K-01: ContextAdjuster arayüzü (batch + online)
- **Karar:** `adjust_batch(df, raw_score) -> DataFrame` ve `adjust_one(record, raw_score) -> AdjustedResult` olmak üzere iki metot; ortak mantık paylaşılır.
- **Alternatifler:** (a) tek `adjust(df, raw_score) -> AdjustedResult` (kural dosyasındaki orijinal hali); (b) tek `adjust(...) -> list[AdjustedResult]` (Adım 0'daki hali).
- **Neden seçildi:** Batch pipeline ve online API aynı kodu kullansın. Batch vektörel çalışır, tek işlem yolu (API) `AdjustedResult` ile açıklamayı döner; iki yol aynı kural mantığına dayandığı için sonuçlar tutarlı kalır.

### K-02: Sabitlerin tek kaynağı
- **Karar:** Split oranı, zaman kolonu, referans tarih ve seed yalnızca `configs/settings.yaml` içinde; kod varsayılanları oradan okur.
- **Alternatifler:** Kodda varsayılan sabit tutmak (çift kaynak).
- **Neden seçildi:** Değer değişince tek yerde değişir; kod ile config'in sessizce ayrışma riski kalkar.

### K-03: SAMPLE_N ile kısmi okuma
- **Karar:** `train_transaction.csv` `nrows=N` ile okunur (dosya TransactionDT'ye göre sıralı), identity okunan TransactionID'lere göre parça parça filtrelenir.
- **Alternatifler:** CSV'yi tam okuyup sıralamak ve kesmek.
- **Neden seçildi:** Geliştirme modunda bellek ve süre N ile orantılı olur. Varsayım: dosya zamana göre sıralı; loader yine de okunan satırları sıralar.

### K-04: RAG chunking stratejisi
- **Karar:** Yapıya duyarlı chunking: markdown `markdown-it-py` ile ağaç yapısına çevrilip başlık sınırlarından bölünür; `rules.yaml`'daki her kural ayrı chunk, kural ID'si metadata'da; uzun bölümler token sınırıyla ikiye ayrılır.
- **Alternatifler:** Sabit boyutlu (token/karakter) chunking, overlap'li.
- **Neden seçildi:** Politika dokümanları başlıklarla yapılandırılmış; başlık sınırı anlam bütünlüğünü korur. Kural bazlı chunk + `rule_id` metadata, tetiklenen kural ID'sine göre filtreli retrieval ve kaynak gösterimini mümkün kılar.

### K-05: Entity proxy
- **Karar:** `card1 + addr1` (adaylarda H); addr1 eksikse NaN ayrı seviye olur. `configs/entity.yaml` içine yazıldı. `D1` anahtara girmez; Adım 3'te iki ayrı feature olarak kullanılır: kart yaşı = `D1` (ilk kullanımdan bu yana geçen gün) ve kart başlangıç günü `D1n` = `floor(TransactionDT/86400) - D1`.
- **D1 yorumu testi (tam veri, `scripts/check_d1_semantics.py`, `reports/profile/d1_semantics.csv`):** "D1 = önceki işlemden beri gün" hipotezi şansın üzerinde değil (|fark - D1| <= 1 oranı %34,4; D1 entity içinde karıştırılınca %33,4). "D1 = kart başlangıcından beri" hipotezi tutuyor: (H, D1n) çifti satırların %63,2'sinde daha önce görülmüş, karıştırılmış D1 ile %33,0. D1n'in H içinde değişmesi (d1n_constancy: işlemlerin ~%96'sı aralığı > 1 gün olan entity'lerde) H'nin birden fazla kartı birleştirmesinden kaynaklanır; her kartın D1n'i sabittir. Bu yorum kanıtlanmış değil, veriyle desteklenen bir varsayımdır (gerçek kart no yok).
- **Alternatifler:** A (`card1`), I (`card1+addr1+D1n`), J (`I + P_emaildomain`).
- **Neden seçildi:** I entity'leri daha homojen yapıyor (log-tutar std 0,35 vs 0,59) ama holdout satırlarının %56'sında entity fit'te görülmüyor; geçmiş tabanlı feature'lar soğuk başlar. H tüm satırları kapsar (tanımsız satır %0) ve holdout'ta %95,8 oranında tanınır. A daha basit ama birden çok kartı birleştirir (max 14.932 işlem). Entity seçimi etiket kullanılmadan, yalnızca sayısal karşılaştırmayla yapıldı.

### K-06: Düşük hacim penceresi ve yerel saat tahmini
- **Karar:** Fit kümesinde saatlik hacmin en düşük olduğu ardışık 6 saat (`argmin`): referans saatle 06:00-11:59 (fit hacminin %4,07'si). Feature adı `is_low_volume_window`. Bu pencerenin yerel 00-06 olduğu varsayılır: `local_hour_est = (hour - 6) mod 24`, `is_business_hours` = yerel saat 09-18 ve yerel hafta içi. Ofset `configs/entity.yaml` içinde görünür (`learned.local_offset_hours: -6`, isteğe bağlı `offset_override_hours`). `is_weekend` referans takvimine göre kalır; yerel takvimle satırların %6,3'ünde farklıdır (`reports/features/weekend_ref_vs_local.csv`).
- **Alternatifler:** 5 saat (07-12, pay %3,0) veya 7 saat (05-12, pay %5,85); `is_night` (00-06) adı.
- **Neden seçildi:** Gereksinim 6 saat. Pencere fit'in ilk ve ikinci yarısında da aynı başlangıçta (06). Saat dilimi bilinmediği için "gece" yerine "hacim dibi" adı kullanıldı; yerel saat bir varsayımdır, kanıt değildir.

### K-07: Velocity pencereleri
- **Karar:** 1h / 6h / 24h / 7d, her biri için geçmiş işlem sayısı ve toplam tutar (8 kolon). 30 günlük pencere yok.
- **Alternatifler:** 1h/24h/7d; 10m/1h/6h/24h/7d.
- **Neden seçildi:** Fit'te önceki işlem aralığı medyan ~9,2 saat; 1h'de satırların %24,8'i, 6h'de %42,6'sı, 24h'de %58,7'si, 7d'de %80,4'ü en az bir geçmiş işlem görüyor (basamaklı doluluk). 30 günde %89,7 ile doygunluğa yakın, ek bilgi vermez. 10 dakikalık pencere card testing için ayrı pencere yerine `small_amt_streak_1h` ile karşılandı.

### K-08: Küçük tutar eşiği (card testing)
- **Karar:** Eşik = fit TransactionAmt'in 0,10 kantili (tam veride 25,95 USD), pencere 1 saat; `small_amt_streak_1h` = aynı entity'nin son 1 saatteki önceki küçük tutarlı işlem sayısı. Değer fit'ten öğrenilir ve `configs/entity.yaml` `learned:` bölümüne yazılır.
- **Alternatifler:** Sabit 10 USD (fit'te yalnızca %1,3 küçük; 1 saatte salvo %0,10); entity-göreli (< 0,2 x geçmiş ortalama; fit'in %16'sında tanımsız, 1 saatte %0,12).
- **Neden seçildi:** Veriden gelir, geçmişi olmayan satırlarda da tanımlıdır, 1 saatte satırların ~%1'ini işaretler (sinyal seyrek ama boş değil). Kantil değeri (q10) bir tercihtir; etiketle ayarlanmadı.

### K-09: Feature listesi, V politikası, tatil feature'ları
- **Karar:** 62 elle tasarlanmış feature (10 temporal/takvim, 24 entity ve velocity, 7 relational, 21 context) + 209 ham kolon (V 185, C 13, D 11; redundancy_clusters temsilcileri ve küme dışı kolonlar). V sayısal ve NaN korunur. `day_index` ve `is_business_hours` listede. Tatil feature'ları: `is_holiday`, `holiday_season` (pencere fit'ten öğrenilir, K-10), `days_to_nearest_holiday` (ABD resmi tatilleri, `configs/holidays.yaml`). Atılanlar: 30d pencere, ham card1/addr1, one-hot, target encoding.
- **Alternatifler:** features.parquet'te yalnızca türetilmiş kolonlar (V listesi ayrı); `is_business_hours`'u atmak.
- **Neden seçildi:** Sonraki adımlar tek dosyadan okur, V için kolon sayısı 339'dan 185'e iner. Tatil feature'ları ve sezon penceresi K-10'da güncellendi. Referans tarih (2017-12-01) ve addr2=87=ABD varsayımdır; tatil feature'ları bu varsayımlara bağlıdır.

### K-10: Tatil feature'ları - resmi tatil hipotezi reddedildi, sezon etkisi veriden öğrenildi
- **Karar:** (1) Resmi tatil hipotezi reddedildi: fit'te tatil günlerinin günlük hacmi diğer günlerle aynı (oran 1,00; 25 Aralık yüksek, 1 Ocak, MLK ve Başkanlar Günü düşük). `is_holiday` ve `days_to_nearest_holiday` features.parquet'te kalır ama feature kataloğunda `model_input = false`; Adım 4 model girdisine girmez. (2) Sezon etkisi kabul edildi: `holiday_season` kalır, penceresi sabit tarih yerine fit hacminden belirlenir. Kural: günlük hacim / çevresindeki 29 günün (ortalanmış) medyanı >= 1,25 olan ardışık gün blokları; 3 günden kısa bloklar atılır; (oran - 1) toplamı en büyük blok sezondur. Sonuç: 2017-12-19 ... 2017-12-26 (8 gün), taban çizgisine göre ortalama oran 1,41; günlük ortalama 5.884 vs diğer günler 3.219 (1,83x). Eski sabit 20 Aralık - 2 Ocak penceresi 1,43x veriyordu ve 27 Aralık - 2 Ocak arasında hacim düşük olduğu için sezonu fazla geniş tanımlıyordu.
- **Alternatifler:** Sabit 20 Aralık - 2 Ocak penceresi; 7 günlük medyan tabanı (istenen ilk tanım); tatil feature'larını tamamen silmek.
- **Neden seçildi:** 7 günlük medyan tabanı 8 günlük tepeyi göremiyor (tepe günleri kendi medyanını yükseltir, oran ~1,0); aynı kural 92. gündeki tek günlük sıçramayı seçiyordu. 29 günlük taban ve en az 3 gün şartı 1,20-1,30 eşik aralığının hepsinde aynı pencereyi veriyor. Etiket kullanılmadı. Sınır: veri tek bir Aralık içeriyor; pencere tek örnekten öğrenildi ve başka yıllara genellenemez (tarihler yıla özgü).

(Sıradaki kararlar: anomali yöntemleri ve ağırlıkları.)

### K-11: Uç değer ve eksik değer işleme (multivariate girdisi)
- **Karar:** (1) `time_since_last_txn` ve `avg_inter_arrival` içindeki -1 sentinel NaN yapılır. (2) Fit'teki |çarpıklık| > 5 olan kolonlara işaretli log `sign(x)*log1p(|x|)` uygulanır. (3) Dönüşümden sonra fit p0.1 / p99.9 sınırlarına kırpılır; sınırlar, çarpıklık kararı ve medyanlar fit'ten öğrenilip artifact'a yazılır. (4) Isolation Forest NaN kabul etmediği için NaN fit medyanıyla doldurulur ve fit'te NaN görülen her kolon için `<kolon>__na` bayrağı eklenir.
- **Alternatifler:** (a) robust z-score (medyan/MAD); (b) yalnızca kırpma (log yok); (c) NaN için sabit -1 değeri.
- **Neden seçildi:** MAD tabanlı yöntem kolonların çoğunda (örneklemde 226/271) MAD=0 olduğu için tanımsız kalır. İşaretli log negatif değerleri (`amt_zscore_ent`) de taşır. Fit sınırları holdout'a sızıntı taşımaz. Sentinel -1 "geçmiş yok" demektir; sayı olarak kalırsa "çok kısa aralık" gibi okunur. Not: column katmanı ECDF (sıra) tabanlı olduğu için log/kırpmadan etkilenmez; ona yalnızca sentinel->NaN uygulanır.

### K-12: Column katmanı - ECDF kuyruk skoru, en yüksek 3 kolonun ortalaması, 28 kolonluk alt küme
- **Karar:** Kolon skoru `s = -log10(2*min(F, 1-F))` (iki yönlü ECDF, fit dağılımı, +1 yumuşatma); fit'te en çok 10 farklı değeri olan (ayrık/ikili) kolonlarda `s = -log10(frekans)`; NaN kendi seviyesi sayılır. Satır skoru = en yüksek 3 kolon skorunun ortalaması. Girdi yalnızca `configs/anomaly.yaml` `column.columns` listesindeki 28 açıklanabilir kolon (tutar, dist, freq_*, C, D, entity'ye göreli tutar; V yok).
- **Alternatifler:** (a) robust z-score + IQR mesafesi; (b) tüm ~250 kolon; (c) en yüksek 1 kolon.
- **Neden seçildi:** ECDF skoru dağılım şeklinden bağımsızdır, p-değeri gibi yorumlanır. Tüm kolonlarda top-3 ortalaması çoklu karşılaştırmadan doyar: örneklem holdout'unda 251 kolonla satırların %39,6'sı skor >= 2 alırken 28 kolonla %17,4'ü alır (skor >= 3: %16,6 vs %4,8); "en sapan kolonlar" açıklaması da anlamsızlaşır. Kolon seçimi (hangi C/D) bir tercihtir, etiketle seçilmedi; config'ten değişir.

### K-13: Multivariate katman - yalnızca Isolation Forest, IF-core girdisi
- **Karar:** `IsolationForest(n_estimators=200, max_samples=256, contamination="auto", random_state=42, n_jobs=-1)`. Ana girdi IF-core = elle tasarlanmış feature'lar (kataloğda `model_input = true`) + C + D, K-18 (düzeltilmiş) dışlamaları sonrası (tam veride 75 kolon + 15 eksiklik bayrağı = 90 girdi; örneklemde 74 + 15). V küme temsilcilerini ekleyen IF-full (tam veride 460 girdi) yalnızca ablation'da karşılaştırılır, ana skora girmez. LOF yok. Açıklama: bir feature'ı fit medyanıyla değiştirip skor düşüşünü ölçen "bir-özelliği-çıkar" yaklaşımı.
- **Alternatifler:** (a) IF + LOF; (b) autoencoder; (c) IF-full ana girdi.
- **Neden seçildi:** IF ölçeklenir (590k x ~80), seed ile tekrarlanır, ölçekleme gerektirmez. LOF O(n^2) ve online skorlamada fit verisine bağımlıdır. V kolonları yorumlanamaz ve çoğu birbirine bağlıdır; ana skoru açıklanabilir tutmak için ablation'a bırakıldı.

### K-14: Entity katmanı - yumuşak geri çekme
- **Karar:** `skor = w*entity_skoru + (1-w)*global_skor`, `w = n/(n+k)`, `k = 5`, `n = ent_txn_count`; ilk işlemde `w = 0`. Ham sayım `ent_txn_count` yalnızca bu `w` için kullanılır. entity_skoru = üç sinyalin ortalaması (tutar z-skoru, log tutar oranı, yeni cihaz); global_skor = (global tutar kuyruğu, cihaz nadirliği `-log10(freq_DeviceInfo)`, `card_new_addr` nadirliği). z-skoru `ent_avg_amt` / `ent_std_amt` ile yeniden hesaplanır, std = 0 olan satırda paydada fit global std kullanılır. Kümülatif kolonlar (`ent_avg_amt`, `ent_std_amt`, `device_ent_match`) yalnızca bu katmanda kullanılır. `amt_ratio_to_ent_avg` ve `amt_zscore_ent` kümülatif sayaç değil, oran/standartlaştırılmış değerlerdir; IF-core ve column listesinde kalır (entity katmanı z-skorunu std=0 düzeltmesi için kendisi yeniden hesaplar).
- **Alternatifler:** (a) sert eşik (n < 5 ise yalnızca global); (b) hiç geri çekme yok; (c) Bayesyen entity-düzeyi öncül.
- **Neden seçildi:** Süreklidir (eşikte sıçrama yok), tek parametre (k) ile anlatılır. Örneklem holdout'unda satırların %18,2'si ilk işlem (w=0), %43,1'inin 5'ten az geçmişi var; sert eşik bu satırları yok sayardı. "Alışılmadık ProductCD" sinyali eklenmedi: `ProductCD` features.parquet'te yok (açık konu).

### K-15: Temporal katman - kural tabanlı alt skorlar
- **Karar:** Beş alt skor, hepsi `-log10(p)` biriminde (fit ECDF), ağırlıklı ortalama (ağırlıklar config'te, varsayılan eşit 0,2): (1) velocity: `ent_cnt_1h`, `ent_cnt_24h`, `ent_sum_1h` üst kuyruk, en büyüğü; (2) inter-arrival kısalığı: `time_since_last_txn` ve bunun entity ortalama aralığına oranı alt kuyruk, en büyüğü; (3) düşük hacim penceresi bayrağı (-log frekans); (4) saat nadirliği: entity saat dağılımı geçmişten (yalnızca önceki işlemler) `(c_h + k*g_h)/(n + k)` ile global saat payına çekilir (k=5); (5) saat/gün baseline hacim sapması: (haftanın günü, saat) hücresinin fit payı ortalama hücre payından küçükse `log10(1/(168*pay))`.
- **Alternatifler:** (a) tek bir ECDF-tabanlı zaman skoru; (b) küresel akış hacmi (son 1 saatte tüm işlem sayısı / beklenen); (c) alt skorlarda farklı ağırlıklar.
- **Neden seçildi:** Alt skorlar tek tek açıklanabilir ve loglanır. (5) için (b) yerine fit paylarına dayalı durumsuz sürüm seçildi: (b) API'de tüm trafiğin canlı durumunu gerektirir ve batch = online eşitliğini bozar. Bu yorum "(C)" ifadesine dayanır; değiştirilebilir. Eşit ağırlık etiketsiz ve savunması kolay olduğu için seçildi.
- **Kullanıcı onayı:** (a) Alt skor (5) durumsuz fit-payı sürümüyle kalır (canlı küresel hacim akışı yok). (b) Alt skorlar eşit ağırlıklı (0,2 x 5) kalır.

### K-16: Skor normalizasyonu - fit kuantil tablosu
- **Karar:** Her katmanın ham skoru, fit satırlarındaki dağılımın 1001 noktalı kuantil tablosuyla `np.interp` ile [0,1]'e çevrilir; eşit değerler (bağlar) kendi seviyelerinin ortalamasını (ortalama rank) alır; fit aralığı dışı değerler 0/1'e kırpılır. Ham skor ve normalize skor ikisi de saklanır. Tablolar `artifacts/detectors/normalization_table.parquet` ve detector joblib dosyalarında; batch ve online aynı `QuantileNormalizer`.
- **Alternatifler:** (a) min-max + winsorize (%1-%99); (b) holdout'u da içeren rank (sızıntı); (c) sigmoid.
- **Neden seçildi:** Katmanların ham ölçekleri farklı (IF 0-1, ECDF birimi -log10); rank tabanlı yöntem hepsini karşılaştırılabilir yapar ve uç değerlerden etkilenmez. Tablo fit'ten gelir, tek işlem de aynı tabloyla skorlanır. Dezavantaj: fit dışı uç değerler 1'de doyar.

### K-17: Birleştirme - ağırlıklı ortalama
- **Karar:** `raw_anomaly_score = 0,35*multivariate + 0,25*entity + 0,20*column + 0,20*temporal` (`configs/weights.yaml`, toplam 1). Katman katkıları `contrib_*` sütunlarında. Ağırlıklar holdout metriklerine bakılarak değiştirilmez. B (korelasyonla ters orantılı ağırlık), max ve noisy-OR yalnızca ablation/karşılaştırma tablosundadır. Ek olarak toplamın kendi fit kuantil tablosuyla normalize hali (`anomaly_score_norm`) saklanır (monoton, metrikler aynı).
- **Alternatifler:** (a) B: ağırlık ~ 1/ort.|korelasyon|; (b) max; (c) noisy-OR; (d) eşit ağırlık.
- **Neden seçildi:** Yorumlanabilir, ağırlık değiştirilebilir, katkı doğrudan görülür. Elle ağırlık: en geniş görüş multivariate'te en yüksek, en dar kapsamlı column ve temporal'de en düşük. B etiketsizdir ama örnekte temporal'e 0,57 ağırlık verip (diğerleriyle korelasyonu düşük) bu katmanı ana belirleyici yapıyor; max ve noisy-OR tek gürültülü katmana duyarlı ve doyuyor.

### K-18: Anomali girdisinden çıkarılan kolonlar (DÜZELTİLDİ)
- **Düzeltme notu:** Aşağıdaki "ilk karar" metni silinmedi. Kullanıcı düzeltti: pencereli kolonlar (`ent_cnt_1h/6h/24h/7d`, `ent_sum_1h/6h/24h/7d`) kümülatif değildir, "son X saat" sayar ve zamanla sistematik büyümez; ömür boyu sayımlar büyür. Bu yüzden pencereli 8 kolon multivariate (IF-core ve IF-full) girdisine GERİ eklendi. Column listesi (28 kolon) pencereli kolon içermiyordu; liste şişirilmedi, değişmedi (velocity zaten temporal katmanda). `drop_windowed` config anahtarı kaldırıldı.
- **Güncel karar:** Çıkarılanlar yalnızca (1) takvimde mutlak konum: `day_index`, `card_start_day`; (2) pencerasiz, ömür boyu büyüyen kümülatifler: `ent_txn_count`, `ent_avg_amt`, `ent_std_amt`, `ent_max_amt`, `ent_age_days`, `ent_unique_device`, `ent_unique_email`, `device_ent_match` (katalog kontrol edildi, başka kümülatif yok; `avg_inter_arrival`, `card_age_days`, `is_first_seen` kümülatif sayaç değil, kalır). Ham `ent_txn_count` yalnızca entity katmanında geri çekme ağırlığı `w` için. `amt_ratio_to_ent_avg` ve `amt_zscore_ent` kalır (kullanıcı onayı).
- **Eski karar (ilk sürüm, geçersiz kısım işaretli):** `day_index` ve `card_start_day` tüm katmanlardan çıkar. Kümülatif kolonlar multivariate ve column girdisinden çıkar. ~~Pencereli `ent_cnt_*` / `ent_sum_*` "ent_sum_* vb." ifadesine göre muhafazakâr yorumlanıp multivariate ve column'dan çıkarıldı~~ (düzeltildi, yukarıya bak). Entity katmanı kümülatif kolonları kullanır (K-14).
- **Alternatifler:** (a) pencereli kolonları dışarıda tutmak (eski sürüm); (b) `card_age_days` (D1) ve `is_first_seen`'i de çıkarmak.
- **Neden seçildi:** Zamanla büyüyen ömür boyu kolonlar fit sonu ile holdout arasında dağılım kaydırır; IF "geç tarih" satırlarını anomali sayar. Pencereli sayımlar sabit uzunlukta pencereden hesaplanır, dağılımı zamanla kaymaz ve ani artış (velocity) bilgisini taşır. `card_age_days` (D1) ve `is_first_seen` kümülatif sayaç değil, IF-core'da kaldı.

### K-19: Sonraki adımlar `anomaly_score_norm` okur; durumsuz hacim sapması kabul
- **Karar:** Adım 6 ve sonrası eşik/bant/kural karşılaştırması için `anomaly_score_norm` (toplamın fit kuantil normalizesi, dağılımı ~uniform) sütununu okur. `raw_anomaly_score` ham toplam olarak saklanır ve açıklama/denetim içindir. Durumsuz hacim sapması (K-15 alt skor 5) kabul edildi; alt skor ağırlıkları eşit (K-15 notu).
- **Alternatifler:** `raw_anomaly_score` okumak; küresel akışa dayalı canlı hacim.
- **Neden seçildi:** Toplam merkezde yoğunlaşır (std 0,20), eşikler yüzdelik olarak anlam kazanmaz; norm skor sıralamayı değiştirmez (monoton), eşiği fit yüzdeliği olarak okunur yapar.

### K-20: Context adjust tasarımı (Adım 6)
- **Karar:** Tasarımı kullanıcı verdi: C1-C9 çarpımsal kurallar, G1 card testing koruması (`small_amt_streak >= 2` ise skor ham skorun altına inmez), toplam çarpan [0,5; 1,5], sonuç [0,1]'e kırpılır (`configs/context.yaml`). Zincir sırası: C5 ağırlık → çarpanlar → sınırlar → koruma → kırpma. Uygulama uyarlamaları (step6.md'de 1-7. maddeler): C5 yalnızca skoru düşürdüğünde uygulanır ve "sık işlem" için önceki işlem >= 5 ve günlük ortalama >= 1 şartı vardır; "bilinen cihaz/email" entity'nin önceki geçmişinden gelir; C7'de "hacim/velocity kaynaklı" = temporal katman en büyük ağırlıklı katkı; değerlendirmede eşitler Adım 5 ham toplamıyla ayrılır; öğrenilen parametreler `reports/context/context_params.json` içindedir.
- **Alternatifler:** (a) toplamsal düzeltme; (b) kural yok, Adım 5 skoru doğrudan kullanılır; (c) C4'te daha dar ya da fit kantilinden gelen eşik.
- **Neden seçildi:** İş mantığına dayanır, her düzeltme açıklanabilir, eşikler ve katsayılar config'ten değiştirilebilir. Kullanıcı zaman kısıtı nedeniyle seçenek turu istemedi. Holdout sonucunda FP arttı (%5 bütçe: 5.222 → 5.291); ablation bunun ana kaynağı olarak C4'ü gösterdi. Kurallar holdout etiketine göre değiştirilmedi.

### K-20a: Context adjust düzeltmesi (Adım 6, K-20'nin devamı)
- **Sorun nasıl fark edildi:** İlk tasarım holdout'ta FP'yi artırdı (%1: 995 → 1.040, %5: 5.222 → 5.291). Etiketsiz kapsam tablosu sebebi gösterdi: ilk C4 (önceki işlem >= 20, cihaz VEYA e-posta) holdout satırlarının %61'ini "güvenilir" sayıyordu.
- **Karar:** Düzeltme etikete değil tanım ilkesine dayanır ("trusted" küçük bir azınlıktır). (1) C4: önceki işlem >= fit q90 (809), entity yaşı >= 30 gün, |amt_zscore_ent| <= 2, bilinen cihaz VE bilinen e-posta. Kapsam fit'te %2,0, holdout'ta %4,0; %10-15 hedefinin altında kaldı (sınırlayan koşul: bilinen cihaz, yalnızca identity kaydı olan işlemlerde var). Yalnızca q seviyesi denendi (0,75'te bile %3,3); q=0,90 korundu ve sonuç olduğu gibi kabul edildi. (2) C6 ve C9 aynı satırda tetiklenirse yalnızca büyük çarpan uygulanır (dışlayıcı grup; eşitse config'teki ilk kural). C9 gerekçesine not: yön fit EDA etiket tablosuyla uyumlu (holdout değil). (3) Öğrenilen parametreler `artifacts/context/` altında. (4) Alarm sıralaması kırpılmamış düzeltilmiş skorla yapılır; [0,1] kırpma yalnızca gösterim/çıktı içindir.
- **Sonuç (holdout):** %1: FP 995 / 1.040 / 983, %5: FP 5.222 / 5.291 / 5.068 (Adım 5 / ilk tasarım / revize). PR-AUC 0,081 / 0,078 / 0,094. Eski ve yeni sonuçlar `docs/step6.md` ve `reports/context/` içinde birlikte duruyor.
- **Alternatifler:** İlk C4'ü korumak; C4'ü tamamen kaldırmak; cihaz koşulunu VEYA yapmak; kırpılmış skorla sıralayıp ham toplamla eşitlik kırmak.
- **Neden seçildi:** Kapsam etiketsiz bir ölçüdür ve eşikler fit'ten öğrenilir. Çift sayım (C6b + C9a = x1,21) iş mantığına aykırıydı. Kırpılmamış sıralama 1,0'daki yığında (revize: 2.682 satır) sıra bilgisinin kaybolmasını önler. Ablation'da holdout'ta zararlı görünen C1, C2, C3 etiketle ayar yasağı nedeniyle değiştirilmedi.

### K-20b: Revize context tasarımının kabulü
- **Karar:** (1) C4 olduğu gibi kalır: bilinen cihaz VE bilinen e-posta; kapsam fit'te %2,0 (hedef %10-15'in altında). (2) C1, C2, C3 değiştirilmez. Holdout ablation'da zararlı göründüler; bu `docs/step6.md` içinde "bilinen sınır" olarak kayıtlı.
- **Alternatifler:** (a) C4'te cihaz koşulunu VEYA yapıp kapsamı hedefe yaklaştırmak; (b) C1-C3'ü holdout ablation sonucuna göre kaldırmak ya da zayıflatmak.
- **Neden seçildi:** (a) kapsam hedefine ulaşmak için seçilmiş bir tanım olurdu; VE, "trusted = güçlü kanıtlı azınlık" ilkesine daha uygun. (b) holdout etiketine göre ayar olurdu (sızıntı). Doğru yöntem, bu kuralları holdout'tan ayrı bir doğrulama döneminde test etmektir; gelecek iş olarak bırakıldı.

### K-21: Rule engine tasarımı (Adım 7) - kullanıcının verdiği tasarım
- **Karar:** Kurallar `configs/rules.yaml` (R01-R10) ve `configs/rules_extra.json` (R11-R12) içinde; şema pydantic v2 ile doğrulanır (id, name, description, priority 1 = en yüksek, severity low/medium/high/critical, iç içe all/any/not koşul, operatörler `> >= < <= == != in not_in between is_null` + `contains`, action {risk_boost, decision block/review/allow, flag}, gerçek değerlerle doldurulan Türkçe `message`, tags, enabled). Bilinmeyen feature/param/şablon alanı ve geçersiz şema yüklemede reddedilir. `RuleRepository` YAML + JSON yükler, `reload()` vardır; `RuleEngine.evaluate(record, score, rules=None)` istekte gelen kural setini doğrulayıp yalnızca o çağrıda kullanır. Kural listesi: R01 card testing (block, p1), R02 yüksek tutar + yabancı + düşük hacim (block, p1), R03 velocity patlaması (review, p2), R04 yeni kart + yüksek tutar, R05 yüksek tutar + yabancı (review, p2), R06 tutar sapması, R07 ilk işlem + yüksek tutar, R08 kimliksiz + yüksek tutar + ProductCD != W (review, p3), R09 e-posta uyuşmazlığı + yüksek tutar (review, p4, low), R10 trusted allow (p5), R11 3 ondalık + addr2 yok + yüksek tutar, R12 tatil + yeni kart + yüksek tutar (JSON, review, p3).
- **Alternatifler:** Kuralları Python sınıfları olarak yazmak; yalnızca YAML; düz (iç içe olmayan) koşul listesi.
- **Neden seçildi:** Kullanıcı tasarımı (zaman kısıtı nedeniyle bu adımda seçenek turu yapılmadı). Kod değiştirmeden kural eklenir/çıkarılır, geçersiz kural sisteme giremez, her karar kural şablonundan gerçek değerlerle açıklanır. R09'un düşük önemi: EDA'da P = R etkisi ProductCD ile karışık (docs/eda.md bulgu 2).

### K-22: Conflict resolution ve final skor (Adım 7) (K-25 ile değişti; K-26 ile genişletildi)
- **Değişiklik notu:** Aşağıdaki ilk metin silinmedi. Geçersiz kısımlar ~~üstü çizili~~ işaretlidir. Güncel kural 4: allow yalnızca KURAL kaynaklı ve daha düşük öncelikli review'ları bastırabilir; tetiklenen herhangi bir block allow'u yener (öncelikten bağımsız); skor eşiği (boost öncesi `adjusted_score_unclipped`) aşılırsa allow geçersizdir ve kurallar allow olmadan yeniden çözülür (K-25, K-26).
- **Karar:** Sıra: önce priority, sonra severity, sonra block > review > allow; ~~allow yalnızca eşit veya daha yüksek öncelikli bir block/review yoksa geçerli~~ (K-25: block öncelikten bağımsız kazanır). Kararı final kararla aynı olan kurallar uygulanır, diğerleri nedeniyle bastırılır ve boost'ları uygulanmaz. `final_score_unclipped = adjusted_score_unclipped + clip(Σ boost, -0,10, +0,40)`; alarm sıralaması kırpılmamış final skorla, `final_score` [0,1] yalnızca çıktı. Hiçbir karar kuralı yoksa ~~`final_score_unclipped >=`~~ boost öncesi `adjusted_score_unclipped >=` fit q99 ise review (skor), değilse allow. ~~Allow kuralı skor tabanlı incelemeye üstün gelir.~~ (K-25/K-26: allow skor incelemesini bastıramaz.)
- **Alternatifler:** (a) tüm tetiklenen kuralların boost'unu toplamak; (b) yalnızca kazanan kuralın boost'u; (c) skor eşiği olmadan yalnızca kural kararı; (d) aynı öncelikte daha yüksek önemli allow'un kazanması.
- **Neden seçildi:** Kullanıcı tasarımı (sıra, tavan, kırpılmamış sıralama). Uygulama yorumları: (a) iç içe kurallarda (R02 ⊂ R05) aynı kanıtı iki kez sayardı; (b) aynı yönde bağımsız kanıtları (R04 + R06) yok sayardı; skor eşiği skill'in "kural kararı + skor eşiği" maddesinden gelir ve config'ten kapatılabilir; (d) "trusted" bir istisna olduğu için eşit öncelikte risk kuralına yenilir. ~~Allow'un skor eşiğine üstün gelmesi~~ K-25'te bir mantık hatası olarak düzeltildi.

### K-23: Kural eşikleri, boost değerleri ve saklama yeri (Adım 7)
- **Karar:** Eşikler fit kümesinden: küçük tutar = TransactionAmt q10 (25,95; Adım 3 ile aynı), yüksek tutar = q95 (441,95; tüm kurallarda), velocity = `ent_cnt_1h` q99,9 (12), skor inceleme eşiği = `adjusted_score_unclipped` q99 (1,0696). Tanımlar `configs/rules.yaml` `learned_params:` içinde; değerleri `scripts/run_rules.py` tam veri koşusunda aynı dosyanın sonundaki `learned:` bloğuna yazar (örneklemde `reports/rules/sample/rule_params.json`). R10 geçmiş eşiği Adım 6 C4'ün `trusted_min_history` (809) değeridir, `artifacts/context/context_params.json`'dan okunur. Boost: critical +0,30, high +0,15, medium +0,08, low +0,03, allow 0 (R10, C4 indirimiyle çift sayımı önlemek için).
- **Alternatifler:** Eşikleri `artifacts/rules/` altına yazmak; sabit eşikler (ör. 500 USD); boost'ları severity yerine kural kural seçmek.
- **Neden seçildi:** Görev "eşikler config'te tutulur" diyor ve Adım 3 `entity.yaml` `learned:` yöntemini kullanıyor; `artifacts/` bu adımın yazma alanı dışındaydı. Fit yüzdelikleri etiketsizdir ve veri ölçeğine uyar. **Boost değerleri (kullanıcı kararı, onaylandı):** Elle verilen severity kademeleri; Adım 5 skor dağılımında bir kademenin sıralamayı kaydırması ama tek başına belirlememesi hedeflendi. Etiketle ayarlanmadı. Sonuç bu değerlere duyarlı; etiketli veri gelince ayrı bir doğrulama döneminde kalibre edilir.
- **Yorum kararları:** R03 "3 katı" = `ent_cnt_1h / ent_daily_avg > 3` (alternatif: 24 saatlik sayım); "yabancı ülke" = Adım 3 `foreign_addr2`; "düşük hacim penceresi" = `is_low_volume_window`.

### K-24: Adım 7 holdout sonucu - kurallar ayarlanmadı
- **Bulgu:** Kural boost'ları alarm sıralamasını Adım 6'ya göre kötüleştirdi: FP %1'de 983 -> 998, %5'te 5.068 -> 5.253; PR-AUC 0,094 -> 0,079. R01 (card testing) yardımcı (precision 0,131, çıkarınca %1'de FP 1.065); R03'ün holdout tetiklenmelerinin 1.123/1.128'i tek bir burst entity'si (precision 0); R04 geniş ve düşük lift'li (1,33). R10 allow satırlarının precision'ı 0,106 (lift 3,1). Karar bazında block precision 0,131, review 0,054.
- **Karar:** Kurallar, eşikler ve boost'lar holdout etiketine göre değiştirilmedi (K-20b ilkesi); bulgular `docs/step7.md` "Bilinen sınırlar" bölümünde. Doğru yöntem holdout'tan ayrı bir doğrulama döneminde ayar yapmaktır (gelecek iş). Kullanıcı kararları K-23 (boost onayı) ve K-25'te (R10 ve R03 düzeltmesi, R04 ve diğerleri değişmez).
- **Alternatifler:** R03/R04'ü kaldırmak veya boost'larını düşürmek; R10'u kapatmak.
- **Neden seçildi:** Holdout'a bakarak kural seçmek etiket sızıntısıdır; değerlendirme yalnızca raporlamadır.

### K-25: R10 ve R03 düzeltmeleri (Adım 7, holdout sonrası) ve EDA tutarlılık kontrolü
- **Karar (kullanıcı kararı):** R10 ve R03 düzeltmeleri holdout sonucu görüldükten sonra yapıldı. Gerekçeleri etiketten bağımsızdır (mantık hatası ve tetiklenme yoğunlaşması). Bu yine de post-hoc bir değişikliktir, şeffaflık için not edildi. Diğer kurallar holdout'a göre değiştirilmedi.
  (1) Conflict resolution kural 4: allow yalnızca KURAL kaynaklı ve daha düşük öncelikli review'ları bastırabilir; skor eşiğinden gelen review'u ve block kararlarını (öncelikten bağımsız) bastıramaz. Mevcut veride hiçbir satırın kararı değişmedi (R10 allow: fit 7.348, holdout 3.830).
  (2) R03'e entity başına cooldown: aynı entity için 1 saatlik pencerede (config: `cooldown.window_seconds: 3600`) en fazla bir kez tetiklenir; yalnızca geçmiş fire'lara bakar. Batch ve online aynı `apply_cooldown` fonksiyonunu kullanır; online durum `CooldownStore` (bellek içi) ile tutulur. Holdout tetiklenme 1.128 -> 21, fit 53 -> 8; parity kontrolü 0 fark.
  (3) Her kural için etiketsiz tetiklenme yoğunlaşması (top-1 ve top-5 entity payı) raporlanır. Etiketli metrikler `src/evaluation/rule_metrics.py` içine taşındı.
  (4) EDA tutarlılık kontrolü (fit ve holdout yan yana, ProductCD kırılımı) yalnızca raporlamadır; kural seçiminde kullanılmadı.
- **Sonuç (holdout):** %1 FP 983 / 998 / 998, %5 FP 5.068 / 5.253 / 5.137, PR-AUC 0,094 / 0,079 / 0,082 (Adım 6 / Adım 7 ilk / Adım 7 düzeltilmiş). Bundan sonra başka ayar yapılmadı.
- **Alternatifler:** (a) hiçbir değişiklik yapmamak (ilk sürümü korumak); (b) R03'ü kaldırmak; (c) R04 ve R09'u da holdout/EDA sonucuna göre değiştirmek; (d) cooldown'u durumsuz bir yaklaşık türetmeyle (ör. "son 1 saatte koşulu sağlayan önceki işlem var mı") yapmak.
- **Neden seçildi:** (a) allow'un skor incelemesini ve block'u ezmesi tasarım niyetiyle çelişen bir mantık hatasıydı. Yoğunlaşma etiketsiz bir ölçüdür ve tek bir patlamanın yüzlerce uyarı üretmesi kural tanımının amacına aykırıdır. (b) Kuralın amacı geçerlidir; sorun tekrar sayımdır. (c) Etiketle kural ayarı olurdu; bunun yerine "Gelecek iş: ayrı doğrulama dönemiyle kural kalibrasyonu" olarak not edildi. (d) "Son tutulan tetiklenme" önceki kararlara bağlıdır; durumsuz yaklaşım batch ile online'ı tam eşleştiremezdi.

### K-26: Skor eşiği allow'u geçersiz kılınca karar (Adım 7 denetimi K7-1)
- **Karar (kullanıcı seçimi: a):** Skor (boost öncesi `adjusted_score_unclipped`) inceleme eşiğine ulaşır ve kazanan allow olursa, allow kuralları yokmuş gibi çözüm yeniden yapılır (`resolve_score_over_allow`). Kural review'ları uygulanır ve boost'ları eklenir, kaynak kural id'si olur. Allow kuralları "skor eşiğinden gelen review'u bastıramaz" nedeniyle bastırılır. Hiç block/review kalmazsa karar skor kaynaklı review'dur ve gerekçe "Block/review kuralı tetiklenmedi" der. Mevcut kural setinde etkisi yoktur (R10 p5); istekte gelen setler ve config değişiklikleri için geçerlidir.
- **Alternatifler:** (a) allow kurallarını çıkarıp yeniden çözmek; (b) kararı skor kaynaklı bırakıp düşük öncelikli review'ları "applied" yapmak ve boost'larını uygulamak (karışık kaynak); (c) değiştirmeyip yalnızca dokümana yazmak.
- **Neden seçildi:** Açıklama tutarlı kalır ve "allow bastırıldıysa etkisi tamamen geri alınır" ilkesine uyar. (b) kaynağı karışık yapar ve anlatması zordur. (c) yanlış gerekçe üretmeye devam ederdi ("Karar kuralı tetiklenmedi" denirken iki kural tetiklenmişti).

### K-27: Online cooldown durum politikası (Adım 7 denetimi K7-3)
- **Karar (kullanıcı seçimi: a + b birlikte):** (a) İstekte gelen kural setleri cooldown durumunu okur ama hiç yazmaz. (b) Yüklü kural seti durumu TransactionID başına yalnızca bir kez günceller (idempotent); aynı işlem iki kez değerlendirilince aynı sonuç döner, çünkü durum "bu işlemden önce" olarak kurulur ((TransactionDT, TransactionID) sırası). İşlenmiş ID'ler ve fire'lar için bellek sınırı: görülen en yeni zamandan pencere süresinden daha eski kayıtlar silinir. Store container Singleton'ıdır (K7-2). Batch yolu (`apply_cooldown`, boş durum) değişmedi; parity 0 fark.
- **Alternatifler:** (a) istekte gelen setler salt okunur, yüklü set günceller; (b) TransactionID tabanlı idempotency; (c) varsayılanı `update_state=False` yapıp durumu yalnızca ayrı bir "işlem kaydı" endpoint'inin güncellemesi.
- **Neden seçildi:** (a) deneme amaçlı kural setlerinin üretim durumunu bozmasını önler (istekte gönderilen "R03" yüklü R03'ün durumunu değiştiremez). (b) API'de aynı işlem tekrar sorgulanırsa kararın değişmesini önler. (c) en temiz ayrımdır ama yeni bir endpoint ve kalıcı store gerektirir; step7.md'de "Gelecek iş: ayrı işlem kaydı endpoint'i ve kalıcı store" olarak yazıldı.
