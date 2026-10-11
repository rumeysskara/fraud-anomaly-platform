---
name: feature-engineering
description: "Adım 3. Temporal, entity, relational ve context feature üretirken, entity proxy (user_id yokluğu) kararı verirken kullan. Leakage'a dikkat."
---

# Feature Engineering

## Girdi
- data/processed/merged.parquet, reports/profile/column_schema.parquet, docs/step1-2.md (entity proxy önerisi)

## Çıktı
- data/processed/features.parquet (TransactionID + üretilen feature'lar)
- reports/features/feature_catalog.parquet: ad, grup (temporal|entity|relational|context), formül, açıklama
- docs/step3.md

## Entity proxy (kritik karar)
IEEE-CIS'te user_id yok. `entity_id` = hash(card1, card2, addr1) ile başla; gerekirse
P_emaildomain veya D1 türevi (TransactionDT - D1*86400 ~ hesap açılış günü) ekle.
Seçimi data-profiling çıktısıyla gerekçelendir ve dokümanda belirt. Birden fazla proxy
tanımlayabilirsin (card_entity, device_entity, email_entity).

## Feature grupları
**Temporal**: hour, day, day_of_week, is_weekend, is_night (örn. 00-06), is_business_hours,
sabit başlangıç tarihine göre türetilmiş datetime, entity için son işlemden bu yana geçen süre.

**Entity** (yalnızca geçmişten, shift/expanding): user_avg_amount, user_std_amount,
user_transaction_count, user_max_amount, amount_ratio_to_user_avg, amount_zscore_user,
entity_age_days, unique_device_count, unique_email_count.

**Velocity**: entity için son 1 saat / 24 saat / 7 gün işlem sayısı ve toplam tutar,
ardışık küçük tutarlı işlem sayısı (card testing sinyali), ortalama inter-arrival süresi.

**Relational**: P_emaildomain == R_emaildomain, billing (addr1) vs shipping (addr2) uyuşmazlığı,
kart-adres kombinasyonunun ilk görülme bayrağı, cihaz-entity eşleşme sayısı, DeviceType/DeviceInfo
ile kart eşleşmesi, id_30/id_31 (OS/tarayıcı) nadir kombinasyon bayrağı.

**Context**: ProductCD bazlı tutar sapması, card4/card6 bazlı tutar yüzdelik dilimi, bölge (addr1)
bazlı ortalamaya göre sapma, has_identity, dist1/dist2 bazlı mesafe sinyali, yabancı ülke proxy'si
(addr2 baskın değer dışı).

**Yüksek cardinality encoding**: frequency encoding ve entity-bazlı count. One-hot YOK.
Target encoding YOK (isFraud kullanılamaz).

## Batch ve online yol (API için kritik)
- `FeaturePipeline.fit(df_fit)` + `transform(df)` batch için; `transform_one(txn: dict) -> dict` API için.
- Entity geçmişi `artifacts/entity_profiles.parquet` olarak kaydedilir (entity_id -> count, mean, std,
  last_dt, bilinen cihaz/email/adres kümeleri, frekans tabloları). `transform_one` bunu kullanır.
- Aynı işlem için batch ve online çıktının eşit olduğunu gösteren test yaz.
- Seçilen entity proxy `configs/entity.yaml` içine yazılır.

## Leakage kuralları
- Tüm entity ve velocity feature'ları TransactionDT sırasına göre, mevcut satır HARİÇ geçmişten hesaplanır.
- `isFraud` hiçbir feature'da kullanılmaz.
- İstatistik tabanlı feature'larda fit/transform ayrımı yap (fit kümesi istatistiği uygulanır).
- İlk işlemlerde (geçmiş yok) NaN yerine açık bir `is_first_seen` bayrağı + güvenli varsayılan kullan.

## Kontrol listesi
- [ ] Her feature feature_catalog'da tanımlı
- [ ] En az 4 temporal, 6 entity, 4 relational, 4 context feature
- [ ] Gelecek bilgisi sızmadığını gösteren unit test (örn. ilk işlemde user_avg boş/varsayılan)
- [ ] Büyük veride bellek kontrolü (dtype downcast)
- [ ] docs/step3.md yazıldı
