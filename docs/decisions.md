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
