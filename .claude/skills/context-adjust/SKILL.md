---
name: context-adjust
description: "Adım 6. Raw anomali skorunu iş bağlamına göre yeniden değerlendiren context adjust engine'i tasarlarken kullan. Business hours, weekend, trusted entity, işlem tipi, coğrafi risk ve false positive azaltımı içerir. Case'in en çok puan veren kısımlarından biri."
---

# Context Adjust Engine

## Girdi
- reports/scores/raw_score.parquet, data/processed/features.parquet

## Çıktı
- configs/context.yaml (tüm context kuralları, parametreler, gerekçe alanı)
- reports/scores/adjusted_score.parquet: TransactionID, raw_score, adjusted_score, applied_adjustments (liste), adjustment_total
- reports/context/fp_impact.parquet + özet tablo: önce/sonra metrikler
- docs/step6.md (kural tasarımı + etki analizi)

## Tasarım
Kurallar kodda değil `configs/context.yaml` içinde; her kural: id, name, açıklama, koşul,
tip (multiplicative | additive), katsayı, gerekçe, tavan/taban. Pipeline (Chain of Responsibility):
her adjuster sırayla uygulanır, sonuç [0,1]'e clip edilir.

## Önerilen context kuralları (kendi iş mantığınla genişlet)
1. **Business hours**: iş saatlerinde (09-18, hafta içi) alışılmış kategori için skoru düşür (x0.9);
   gece 00-05'te yüksek tutar için artır (x1.15).
2. **Weekend**: hafta sonu perakende/tüketici ürünlerinde (ProductCD'ye göre) hafif düşür;
   hafta sonu + yüksek tutar + yeni cihaz için artır.
3. **Trusted entity**: uzun geçmişli (örn. >=30 işlem), düşük tutar varyanslı, bilinen cihaz/email'li
   entity için skoru düşür (x0.7-0.85). Yeni entity (is_first_seen) için düşürme YOK, hafif artır.
4. **Yüksek değerli/sık müşteri**: yüksek ortalama tutarlı entity'de tutar sapması toleransı genişler
   (kendi baseline'ına göre değerlendir).
5. **İşlem tipi risk profili**: ProductCD bazlı baz risk çarpanı (veride fraud'a değil, işlem davranışına
   dayalı; ör. küçük tutar / yüksek frekans ürün tipi için tolerans). isFraud kullanma.
6. **Coğrafi risk**: addr2 (ülke) baskın değer dışında ve entity'nin geçmiş adreslerinden farklıysa artır;
   entity geçmişte bu adreste sık işlem yaptıysa düşür.
7. **Kimlik doğrulama güvencesi**: has_identity ve tutarlı cihaz/OS varsa küçük düşürme.
8. **Güvenlik tavanı**: adjuster'ların toplam etkisi sınırlı (örn. nihai skor ham skorun 0.5x-1.5x'i aralığında).
   Kritik sinyaller (card testing velocity patlaması gibi) trusted düzeltmesiyle tamamen bastırılamaz.

## False positive azaltımı (ölçülmeli)
- "Alarm" tanımı: skorun üst %1 veya %5'i (sabit alarm bütçesi) ve/veya sabit eşik.
- Önce/sonra metrikler: alarm sayısı, trusted/uzun geçmişli entity'lerdeki alarm sayısı,
  precision@k, recall@k, FP oranı (isFraud YALNIZCA bu raporlama için kullanılır).
- Adjuster bazlı ablation: her kuralın tek başına etkisi tablosu.
- Amaç: recall'ı ciddi kaybetmeden alarm içi yanlış pozitifleri azaltmak. Düşüşü ve bedelini açıkça yaz.

## Kurallar
- Parametreler isFraud ile ayarlanmaz (etiketsiz, iş mantığı ile belirlenir); sonuç yalnızca raporlanır.
- Her adjustment çıktıda `applied_adjustments` içinde ad + etkisiyle görünür (explainability).

## Kontrol listesi
- [ ] En az 6 context kuralı, hepsi context.yaml içinde ve gerekçeli
- [ ] Çarpan/ek etkisi için toplam tavan var
- [ ] adjusted_score ve applied_adjustments üretiliyor
- [ ] Önce/sonra FP metrik tablosu + ablation tablosu hazır
- [ ] Her adjuster için pytest (tetiklenen/tetiklenmeyen)
- [ ] docs/step6.md: tasarım, gerekçe, etki detaylı
