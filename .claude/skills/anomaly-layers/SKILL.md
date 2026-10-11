---
name: anomaly-layers
description: "Adım 4-5. Column, multivariate, entity ve temporal anomali katmanlarını geliştirirken, skorları normalize edip weighted aggregation ile raw anomali skoru üretirken kullan."
---

# Multi-Layer Anomaly Detection + Score Aggregation

## Girdi
- data/processed/features.parquet, reports/features/feature_catalog.parquet

## Çıktı
- reports/scores/layer_scores.parquet: TransactionID, column_score, multivariate_score, entity_score, temporal_score (hepsi [0,1])
- reports/scores/raw_score.parquet: TransactionID, raw_anomaly_score [0,1]
- configs/weights.yaml (katman ağırlıkları + gerekçe)
- docs/step4-5.md

## Ortak arayüz
Her katman `Detector` arayüzünü uygular: `fit(df)`, `score(df) -> Series[0,1]`, `explain(row) -> dict`.
`src/detection/` altında her katman ayrı modül; Factory ile oluşturulur, container'dan inject edilir.

## Katmanlar
1. **Column anomaly** (tek kolon): robust z-score (median/MAD), IQR dışı mesafe, kategorikte nadirlik
   (-log frekans). Kolon başına skor, satır skoru = en yüksek N kolonun birleşimi. explain: en sapan kolonlar.
2. **Multivariate anomaly**: Isolation Forest (zorunlu), isteğe bağlı LOF veya autoencoder.
   Sayısal feature alt kümesi, ölçekleme, contamination=auto, seed=42. explain: en çok katkı yapan feature'lar
   (örn. permütasyon veya yol uzunluğu bazlı yaklaşım).
3. **Entity anomaly**: entity'nin kendi geçmişine göre sapma (amount_zscore_user, yeni cihaz, yeni adres,
   alışılmadık ProductCD). Yeterli geçmişi olmayan entity'lerde skor kısmen global popülasyona geri düşer (shrinkage).
4. **Temporal anomaly**: saatlik/günlük baseline'a göre sapma, velocity patlamaları, entity'nin olağan
   saat dilimi dışında işlem, inter-arrival süresinin anormal kısalığı.

## Skor normalizasyonu (Adım 5)
- Her katman skoru [0,1]'e: rank-based (percentile) normalizasyon veya min-max + winsorize (%1-%99).
- Yöntemi seçme gerekçeni yaz (rank: dağılımdan bağımsız ve katmanlar karşılaştırılabilir olur).
- Ham skor ve normalize skor ikisi de saklanır.

## Weighted aggregation
- `raw_score = sum(w_i * s_i)`, ağırlıklar toplamı 1, configs/weights.yaml içinde.
- Ağırlıklar ETİKETSİZ seçilir (elle uzman görüşü veya katmanlar arası korelasyonu düşüren ağırlık);
  `isFraud` ile ayarlanmaz.
- Neden weighted average: yorumlanabilir, ağırlık değiştirilebilir, katman katkısı açıklanabilir.
  Alternatifleri (max, noisy-OR, rank average) kısa karşılaştır ve dokümanda belirt.
- Çıktıda her satır için katman katkıları (`contrib_*`) tutulur -> explainability.

## Kalıcılık (API için)
- Detector'lar fit kümesinde (zaman split'inin ilk %80'i) eğitilir, `artifacts/detectors/*.joblib` olarak kaydedilir.
- Normalizasyon için gereken referans dağılım (percentile tablosu) da kaydedilir; tek işlem skorlanırken
  rank-normalizasyon bu tabloya göre yapılır.
- `ScoringService.score_one(features: dict)` ve `score_batch(df)` aynı kodu kullanır.

## Değerlendirme (sadece raporlama)
- `src/evaluation/metrics.py` ile holdout üzerinde: PR-AUC, ROC-AUC, recall@top1%/5% (katman bazlı + birleşik).
- Bu metrikler ağırlık/eşik ayarında kullanılmaz; sadece raporlanır.

## Kontrol listesi
- [ ] 4 katmanın her biri ayrı skor üretiyor, hepsi [0,1]
- [ ] Katman skorları ayrı ayrı kaydedilmiş
- [ ] Ağırlıklar config'te, toplam = 1
- [ ] Katman katkıları (contrib_*) çıktıda
- [ ] Aggregation gerekçesi dokümanda
- [ ] Her katman için pytest (fit/score/explain)
- [ ] docs/step4-5.md yazıldı
